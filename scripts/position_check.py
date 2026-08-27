# -*- coding: utf-8 -*-
"""보유종목(positions.csv, buy 명령으로 등록된 것) 감시 (GitHub Actions에서 5분마다 자동 실행)

⚠️ 절대 자동으로 팔지 않습니다. 아래 조건에 해당하면 알림만 보내고,
실제 종료는 텔레그램 `sell` 명령을 사용자가 직접 입력해야 이뤄집니다
(터틀 스크리너의 holdings_check.py와 동일한 방식).

- 3일 신저가 이탈 또는 하드스탑(1.5×ATR10/-7% 중 타이트한 쪽) 이탈
  → "매도 검토" 알림 1회만 발송, status를 'stop_hit'으로 변경 (감시는 계속 유지)
- 진입가 대비 ATR 정수배 수익 도달 → "N배 수익 도달" 진행상황 알림 (매도신호 아님)
- 매 실행마다 활성(비청산) 포지션 전체 현황을 무조건 요약 발송 (📦)

status 값: active(감시중) / stop_hit(매도검토 알림 나감, 여전히 감시중) / closed_manual(sell로 종료)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
import FinanceDataReader as fdr
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from common import EXIT_PERIOD, check_channel_exit, fmt_num, fmt_pct, trend_arrow, notify_telegram, send_long_message
from storage import load_positions, save_positions

PRE_POST_BUFFER_MIN = 5
HISTORY_DAYS = 20  # 3일 채널청산 계산에 필요한 최소 히스토리 + 여유분


def is_korea_market_open():
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    if now.weekday() >= 5:
        return False
    open_t = (datetime.combine(now.date(), dtime(9, 0)) - timedelta(minutes=PRE_POST_BUFFER_MIN)).time()
    close_t = (datetime.combine(now.date(), dtime(15, 30)) + timedelta(minutes=PRE_POST_BUFFER_MIN)).time()
    return open_t <= now.time() <= close_t


def is_us_market_open():
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() >= 5:
        return False
    open_t = (datetime.combine(now.date(), dtime(9, 30)) - timedelta(minutes=PRE_POST_BUFFER_MIN)).time()
    close_t = (datetime.combine(now.date(), dtime(16, 0)) + timedelta(minutes=PRE_POST_BUFFER_MIN)).time()
    return open_t <= now.time() <= close_t


def get_bithumb_daily_ohlc(coin, days=HISTORY_DAYS):
    url = f"https://api.bithumb.com/public/candlestick/{coin}_KRW/24h"
    res = requests.get(url, timeout=10).json()
    if res.get('status') != '0000':
        return None
    raw = res['data']
    df = pd.DataFrame(raw, columns=['Time', 'Open', 'Close', 'High', 'Low', 'Volume'])
    df['Time'] = pd.to_datetime(df['Time'], unit='ms')
    df = df.set_index('Time')
    for col in ['Open', 'Close', 'High', 'Low', 'Volume']:
        df[col] = df[col].astype(float)
    return df.tail(days)


def get_recent_history(market, code, days=HISTORY_DAYS):
    try:
        if market == 'KR':
            end = datetime.today()
            start = end - timedelta(days=days + 10)
            df = fdr.DataReader(str(code).zfill(6), start, end)
            return df if not df.empty else None
        elif market == 'US':
            data = yf.download(code, period=f'{days + 10}d', auto_adjust=True, progress=False)
            return data if not data.empty else None
        elif market == 'COIN':
            return get_bithumb_daily_ohlc(code, days)
    except Exception as e:
        print(f"  {code} 조회 실패: {e}")
        return None
    return None


def build_status_tag(current_price, hard_stop_price, status):
    if status == 'stop_hit':
        return "🔴 손절확정 (매도대기)"
    if pd.isna(current_price) or pd.isna(hard_stop_price):
        return "❔ 데이터부족"
    gap_pct = (current_price - hard_stop_price) / hard_stop_price * 100 if hard_stop_price else None
    if gap_pct is not None and gap_pct <= 3.0:
        return "🔶 하드스탑 근접"
    return "🟢 정상"


if __name__ == "__main__":
    df = load_positions()
    if df.empty:
        print("등록된 포지션이 없습니다. 텔레그램에서 buy 명령으로 먼저 등록해주세요.")
        sys.exit(0)

    numeric_cols = ['entry_price', 'atr_entry', 'hard_stop_price', 'highest_price',
                     'last_milestone', 'last_price', 'last_n_low']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['last_milestone'] = df['last_milestone'].fillna(0)

    kr_open = is_korea_market_open()
    us_open = is_us_market_open()

    changed = False
    summary_rows = []

    # closed_manual만 감시 제외 (stop_hit은 sell 하기 전까지 계속 추적)
    active_mask = df['status'] != 'closed_manual'
    for idx, row in df[active_mask].iterrows():
        market = row['market']
        if market == 'KR' and not kr_open:
            continue
        if market == 'US' and not us_open:
            continue
        # COIN은 24시간이라 항상 체크

        hist = get_recent_history(market, row['code'])
        if hist is None or hist.empty:
            continue

        last = hist.iloc[-1]
        today_low = float(last['Low'])
        today_close = float(last['Close'])
        today_high = float(last['High'])

        pid = row['position_id']
        code = row['code']
        entry_price = row['entry_price']
        hard_stop_price = row['hard_stop_price']
        highest_price = row['highest_price']
        prev_close = row['last_price']
        prev_n_low = row['last_n_low']
        status = row['status'] if row['status'] else 'active'

        if pd.isna(entry_price) or pd.isna(hard_stop_price):
            print(f"거래 {pid}({code}): 핵심 데이터 NaN, 이번 회차 건너뜀")
            continue

        # 1) 최고가 정보성 갱신 (손절과 무관, 마일스톤 진행상황 알림용)
        if today_high > highest_price:
            highest_price = today_high
            df.at[idx, 'highest_price'] = float(highest_price)
            changed = True

        # 2) ATR 배수 마일스톤 체크 (매도 신호 아님, 진행상황 알림)
        atr_entry = row['atr_entry']
        last_milestone = int(row['last_milestone']) if pd.notna(row['last_milestone']) else 0
        if pd.notna(atr_entry) and atr_entry > 0 and status == 'active':
            current_multiple = int((highest_price - entry_price) // atr_entry)
            if current_multiple > last_milestone:
                profit_pct = (highest_price - entry_price) / entry_price * 100
                notify_telegram(
                    f"[{market}] {current_multiple}배(ATR) 수익 도달 (진행상황)\n"
                    f"거래번호 {pid} - {code}\n"
                    f"매수가 {fmt_num(entry_price)} / 현재 최고가 {fmt_num(highest_price)}\n"
                    f"수익률 {profit_pct:+.2f}%"
                )
                df.at[idx, 'last_milestone'] = int(current_multiple)
                changed = True

        # 3) 채널청산(3일 신저가) 판정 — 알림만
        channel = check_channel_exit(hist, EXIT_PERIOD)
        channel_hit = bool(channel and channel['exit_signal'])
        n_low = channel['n_low'] if channel else None

        # 4) 하드스탑 판정 — 알림만
        hard_stop_hit = today_low <= hard_stop_price

        if status == 'active' and (channel_hit or hard_stop_hit):
            reason = "3일 신저가 이탈" if channel_hit else "하드스탑 이탈"
            if channel_hit and hard_stop_hit:
                reason = "3일 신저가 + 하드스탑 동시 이탈"
            pnl_pct = (today_close - entry_price) / entry_price * 100
            notify_telegram(
                f"[{market}] {reason}! (매도 검토)\n"
                f"거래번호 {pid} - {code}\n"
                f"매수가 {fmt_num(entry_price)} / 하드스탑 {fmt_num(hard_stop_price)} / "
                f"현재가 {fmt_num(today_close)}\n"
                f"손익률 {pnl_pct:+.2f}%\n"
                f"sell {pid} 명령으로 종료할 수 있어요."
            )
            df.at[idx, 'status'] = 'stop_hit'
            status = 'stop_hit'
            changed = True
            print(f"거래 {pid}({code}) {reason} - 매도검토 알림 발송")
        else:
            print(f"거래 {pid}({code}): 현재가 {today_close} "
                  f"(하드스탑 {hard_stop_price}) - 감시 유지 (status={status})")

        # ===== 요약용 표시값 조립 =====
        tag = build_status_tag(today_close, hard_stop_price, status)
        arrow = trend_arrow(today_close, prev_close)
        n_low_arrow = trend_arrow(n_low, prev_n_low) if n_low is not None else "N/A"
        n_low_str = fmt_num(n_low) if n_low is not None else "N/A"
        pnl_pct = (today_close - entry_price) / entry_price * 100
        hard_stop_dist_pct = ((today_close - hard_stop_price) / hard_stop_price * 100
                               if hard_stop_price else None)

        summary_rows.append(
            f"- [{pid}] {row['name']}({code}) [{market}] {tag}\n"
            f"  현재가 {fmt_num(today_close)} {arrow} / 매수가 {fmt_num(entry_price)} (손익 {pnl_pct:+.2f}%)\n"
            f"  3일저가선 {n_low_str} {n_low_arrow}\n"
            f"  하드스탑 {fmt_num(hard_stop_price)} (남은거리 {fmt_pct(hard_stop_dist_pct)})"
        )

        df.at[idx, 'last_price'] = float(today_close)
        if n_low is not None:
            df.at[idx, 'last_n_low'] = float(n_low)
        changed = True

    if changed:
        save_positions(df)

    if summary_rows:
        header = f"📦 [보유종목 현황] {len(summary_rows)}건 (5분 자동 갱신)"
        send_long_message(header + "\n" + "\n".join(summary_rows))
    else:
        print("이번 회차에 체크된(장중/코인) 보유종목이 없어 요약을 생략합니다.")
