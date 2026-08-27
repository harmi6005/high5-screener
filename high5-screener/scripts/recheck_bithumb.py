# -*- coding: utf-8 -*-
"""빗썸 관심코인 5일신고가 재확인 (GitHub Actions에서 5분마다 자동 실행, 24시간 동작)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (ENTRY_PERIOD, WATCH_RATIO, MAX_CHASE_RATIO,
                     check_high5_breakout, calc_hard_stop, notify_telegram, send_long_message,
                     load_trade_history, save_trade_history, check_whipsaw)
from storage import load_positions, save_positions, gen_position_id, already_holding, load_watch, save_watch_for_market

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
    coin, name = row['code'], row['name']
    try:
        df = get_bithumb_daily_ohlc(coin)
        if df is None or df.empty:
            return None
        res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
        if not res:
            return None
        return {'code': coin, 'name': name, **res}
    except Exception:
        return None


if __name__ == "__main__":
    watch_df = load_watch()
    target_rows = watch_df[watch_df['market'] == MARKET_LABEL].to_dict('records')
    if not target_rows:
        print("현재 관심코인이 없습니다.")
        sys.exit(0)

    print(f"관심코인 {len(target_rows)}개 재확인 중...")
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(recheck_one, row): row for row in target_rows}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

    pos_df = load_positions()
    hist_df = load_trade_history(HIST_PATH)
    hist_changed = False

    entry_rows = []
    still_watch_rows = []
    skip_chase = 0
    skip_whipsaw = 0

    for r in results:
        code = r['code']
        if r['fresh_entry_signal']:
            if already_holding(pos_df, MARKET_LABEL, code):
                continue
            chase_ratio = (r['close'] - r['n_high']) / r['n_high']
            if chase_ratio > MAX_CHASE_RATIO:
                skip_chase += 1
                continue
            allowed, hist_df = check_whipsaw(hist_df, MARKET_LABEL, code, r['n_high'], r['close'], r['atr'])
            hist_changed = True
            if not allowed:
                skip_whipsaw += 1
                continue

            pid = gen_position_id(pos_df)
            hard_stop = calc_hard_stop(r['close'], r['atr'])
            new_pos = {'position_id': pid, 'market': MARKET_LABEL, 'code': code, 'name': r['name'],
                       'entry_price': r['close'], 'atr_entry': r['atr'],
                       'hard_stop_price': hard_stop, 'highest_price': r['close'],
                       'last_milestone': 0, 'last_price': r['close'], 'last_n_low': '',
                       'status': 'active', 'entry_date': pd.Timestamp.now().strftime('%Y-%m-%d')}
            pos_df = pd.concat([pos_df, pd.DataFrame([new_pos])], ignore_index=True)
            entry_rows.append({**r, 'position_id': pid, 'hard_stop_price': hard_stop})
        elif r['watch_signal']:
            still_watch_rows.append(r)

    save_positions(pos_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    still_watch_df = pd.DataFrame(still_watch_rows)
    save_watch_for_market(MARKET_LABEL, still_watch_df)

    print(f"[코인 재확인] 신규진입 {len(entry_rows)}개 / 관심유지 {len(still_watch_df)}개 / "
          f"스킵(추격과다) {skip_chase}개 / 스킵(휩쏘) {skip_whipsaw}개")

    if entry_rows:
        lines = [f"[코인 5일신고가] 돌파! 신규 진입 {len(entry_rows)}건 (포지션 자동 등록됨)"]
        for r in entry_rows:
            lines.append(
                f"- {r['name']} [거래번호 {r['position_id']}]\n"
                f"  진입가 {r['close']} / 5일고가 {r['n_high']}\n"
                f"  청산: 3일 신저가 이탈 시 / 하드스탑 {r['hard_stop_price']}"
            )
        send_long_message("\n".join(lines))
    else:
        print("[코인 재확인] 신규 전환 없음")
