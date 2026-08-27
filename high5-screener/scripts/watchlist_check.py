# -*- coding: utf-8 -*-
"""관심종목(watch.csv) 5분마다 무조건 현황 요약 (GitHub Actions에서 5분마다 자동 실행)

터틀 스크리너의 '집중추적종목(watchlist)' 5분 무조건 요약을 응용.
포지션으로 전환되기 전(아직 5일 신고가를 못 넘은) 관심종목들의 현재가 추세와
5일고가선 대비 근접도를 계속 보여준다. 상태 전환(진입/탈락) 자체는
recheck_*.py가 담당하고, 이 스크립트는 순수 현황 보고만 담당한다.

국장/미장은 개장 5분 전 ~ 마감 5분 후까지만 체크, 코인은 24시간.
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
from common import fmt_num, trend_arrow, notify_telegram, send_long_message
from storage import load_watch, save_watch_full

PRE_POST_BUFFER_MIN = 5


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


def get_kr_price(code):
    try:
        end = datetime.today()
        start = end - timedelta(days=10)
        df = fdr.DataReader(str(code).zfill(6), start, end)
        if df.empty:
            return None
        return float(df.iloc[-1]['Close'])
    except Exception:
        return None


def get_us_prices(codes):
    """여러 티커를 한 번에 배치 다운로드 (API 호출 최소화)."""
    try:
        data = yf.download(codes, period='5d', auto_adjust=True, progress=False, group_by='ticker')
    except Exception:
        return {}
    prices = {}
    for c in codes:
        try:
            df = data[c].dropna() if len(codes) > 1 else data.dropna()
            if not df.empty:
                prices[c] = float(df.iloc[-1]['Close'])
        except Exception:
            continue
    return prices


def get_coin_price(coin):
    try:
        url = f"https://api.bithumb.com/public/ticker/{coin}_KRW"
        res = requests.get(url, timeout=10).json()
        if res.get('status') != '0000':
            return None
        return float(res['data']['closing_price'])
    except Exception:
        return None


def build_tag(ratio):
    if ratio is None or pd.isna(ratio):
        return "❔ 데이터부족"
    if ratio >= 1.0:
        return "⚡ 돌파(전환대기)"
    if ratio >= 0.99:
        return "🔶 돌파임박"
    return "🟢 관찰중"


if __name__ == "__main__":
    watch_df = load_watch()
    if watch_df.empty:
        print("등록된 관심종목이 없습니다.")
        sys.exit(0)

    for col in ['close', 'n_high', 'n_high_ratio', 'atr', 'last_close']:
        watch_df[col] = pd.to_numeric(watch_df[col], errors='coerce')

    kr_open = is_korea_market_open()
    us_open = is_us_market_open()

    changed = False
    summary_rows = []

    # 미국은 배치 다운로드가 훨씬 효율적이라 먼저 한 번에 조회
    us_codes = watch_df[watch_df['market'] == 'US']['code'].unique().tolist()
    us_prices = get_us_prices(us_codes) if (us_codes and us_open) else {}

    for idx, row in watch_df.iterrows():
        market = row['market']
        if market == 'KR' and not kr_open:
            continue
        if market == 'US' and not us_open:
            continue
        # COIN은 24시간이라 항상 체크

        code = row['code']
        if market == 'KR':
            price = get_kr_price(code)
        elif market == 'US':
            price = us_prices.get(code)
        elif market == 'COIN':
            price = get_coin_price(code)
        else:
            price = None

        if price is None:
            print(f"  {code} 현재가 조회 실패, 이번 회차 건너뜀")
            continue

        n_high = row['n_high']
        ratio = price / n_high if n_high else None
        prev_close = row['last_close']
        arrow = trend_arrow(price, prev_close)
        tag = build_tag(ratio)

        ratio_str = f"{ratio*100:.1f}%" if ratio is not None else "N/A"
        summary_rows.append(
            f"- {row['name']}({code}) [{market}] {tag}\n"
            f"  현재가 {fmt_num(price)} {arrow} / 5일고가선 {fmt_num(n_high)} ({ratio_str})"
        )

        watch_df.at[idx, 'last_close'] = float(price)
        watch_df.at[idx, 'close'] = float(price)
        if ratio is not None:
            watch_df.at[idx, 'n_high_ratio'] = round(float(ratio), 4)
        changed = True

    if changed:
        save_watch_full(watch_df)

    if summary_rows:
        header = f"🎯 [관심종목 현황] {len(summary_rows)}종목 (5분 자동 갱신)"
        send_long_message(header + "\n" + "\n".join(summary_rows))
    else:
        print("이번 회차에 체크된(장중/코인) 관심종목이 없어 요약을 생략합니다.")
