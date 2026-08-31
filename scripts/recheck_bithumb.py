# -*- coding: utf-8 -*-
"""빗썸 관심코인 재확인 (GitHub Actions에서 5분마다 자동 실행, 24시간 동작)
⚠️ 알림만 하며, 실제 매수/매도는 텔레그램 buy/sell 명령으로만 이뤄짐.

⚠️ watchlist_check.py의 중복 시세조회를 없애기 위해, 재확인 과정에서 이미
가져온 시세(res)를 재사용해서 '관심' 상태로 남은 코인의 현황요약까지 같이 보냄."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (MAX_CHASE_RATIO, check_high5_system, notify_telegram, send_long_message,
                     fmt_num, trend_arrow, load_trade_history, save_trade_history,
                     check_whipsaw, record_trade_result)
from storage import load_scan, save_scan_for_market

MAX_WORKERS = 10
MARKET_LABEL = 'COIN'
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


def get_bithumb_daily_ohlc(coin, days=120):
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


def recheck_one(row):
    coin, name, orig_signal = row['code'], row['name'], row['signal']
    try:
        df = get_bithumb_daily_ohlc(coin)
        if df is None or df.empty:
            return None
        res = check_high5_system(df)
        if not res:
            return None

        if orig_signal == '확정':
            status = '확정이탈' if res['exit_signal'] else '확정유지'
        elif res['fresh_entry_signal']:
            chase_ratio = (res['close'] - res['n_high']) / res['n_high']
            status = '스킵(추격과다)' if chase_ratio > MAX_CHASE_RATIO else '확정_candidate'
        else:
            status = '유지' if res['watch_signal'] else '탈락'

        return {'code': coin, 'name': name, 'status': status,
                'entry_price': row.get('entry_price', ''), **res}
    except Exception:
        return None


def build_watch_tag(ratio):
    if ratio is None or pd.isna(ratio):
        return "❔ 데이터부족"
    return "🔶 돌파임박" if ratio >= 0.99 else "🟢 관찰중"


if __name__ == "__main__":
    scan_df = load_scan()
    prev_df = scan_df[scan_df['market'] == MARKET_LABEL].copy()
    for col in ['close', 'n_high', 'n_high_ratio', 'last_close']:
        if col in prev_df.columns:
            prev_df[col] = pd.to_numeric(prev_df[col], errors='coerce')

    target_rows = prev_df[prev_df['signal'].isin(['관심', '확정'])].to_dict('records')
    if not target_rows:
        print("현재 관심/확정 코인이 없습니다.")
        sys.exit(0)

    print(f"관심/확정 코인 {len(target_rows)}개 재확인 중...")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(recheck_one, row): row for row in target_rows}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    hist_df = load_trade_history(HIST_PATH)
    hist_changed = False
    confirm_rows = []
    exit_rows = []
    whipsaw_skip_count = 0

    for r in results:
        if r['status'] == '확정_candidate':
            allowed, hist_df = check_whipsaw(hist_df, MARKET_LABEL, r['code'], r['n_high'], r['close'], r['atr'])
            hist_changed = True
            if allowed:
                r['status'] = '확정'
                confirm_rows.append(r)
            else:
                r['status'] = '관심'
                whipsaw_skip_count += 1
        elif r['status'] == '확정이탈':
            exit_rows.append(r)

    confirm_df = pd.DataFrame(confirm_rows)
    exit_df = pd.DataFrame(exit_rows)
    skip_cnt = len([r for r in results if r['status'] == '스킵(추격과다)'])
    print(f"[코인 재확인] 확정 {len(confirm_df)}개 / 확정이탈 {len(exit_df)}개 / "
          f"휩쏘스킵 {whipsaw_skip_count}개 / 스킵(추격과다) {skip_cnt}개")

    watch_lines = []
    for r in results:
        code, status = r['code'], r['status']
        mask = (prev_df['code'] == code)
        if status == '확정':
            prev_df.loc[mask, 'signal'] = '확정'
            prev_df.loc[mask, 'entry_price'] = r['close']
        elif status in ('탈락', '스킵(추격과다)'):
            prev_df.loc[mask, 'signal'] = '탈락'
        elif status == '확정이탈':
            prev_df.loc[mask, 'signal'] = '확정이탈'
            entry_price = r.get('entry_price', '')
            try:
                entry_price = float(entry_price)
                hist_df = record_trade_result(hist_df, MARKET_LABEL, code, entry_price, r['close'])
                hist_changed = True
            except (ValueError, TypeError):
                pass
        elif status == '유지':
            old_last_close = prev_df.loc[mask, 'last_close']
            old_val = float(old_last_close.iloc[0]) if not old_last_close.empty and pd.notna(old_last_close.iloc[0]) else None
            arrow = trend_arrow(r['close'], old_val)
            ratio = r.get('n_high_ratio')
            tag = build_watch_tag(ratio)
            ratio_str = f"{ratio*100:.1f}%" if ratio is not None and not pd.isna(ratio) else "N/A"
            watch_lines.append(
                f"- {r['name']} [COIN] {tag}\n"
                f"  현재가 {fmt_num(r['close'])} {arrow} / 5일고가선 {fmt_num(r['n_high'])} ({ratio_str})"
            )
            prev_df.loc[mask, 'last_close'] = r['close']
            prev_df.loc[mask, 'close'] = r['close']

    save_scan_for_market(MARKET_LABEL, prev_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    if not confirm_df.empty:
        lines = [f"- {r['name']}\n"
                 f"  현재가 {r['close']} / 진입가(돌파) {r['n_high']} / 참고 3일저가 {r['n_low']}\n"
                 f"  괴리율 {(r['close']-r['n_high'])/r['n_high']*100:.2f}%\n"
                 f"  buy {r['code']} {r['close']} 명령으로 등록할 수 있어요."
                 for _, r in confirm_df.iterrows()]
        notify_telegram("[코인] 확정 전환 종목! (매수 검토)\n" + "\n".join(lines))

    if not exit_df.empty:
        lines = [f"- {r['name']}\n  현재가 {r['close']} / 3일저가(참고) {r['n_low']}"
                 for _, r in exit_df.iterrows()]
        notify_telegram("[코인] 확정이탈 종목! (보유 중이면 매도 검토)\n" + "\n".join(lines))

    if watch_lines:
        header = f"🎯 [관심종목 현황-코인] {len(watch_lines)}종목 (재확인과 통합, 알림 전용)"
        send_long_message(header + "\n" + "\n".join(watch_lines))
