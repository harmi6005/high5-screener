# -*- coding: utf-8 -*-
"""미국 관심종목 5일신고가 재확인 (GitHub Actions에서 5분마다 자동 실행, 장중에만 동작)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from common import (ENTRY_PERIOD, WATCH_RATIO, MAX_CHASE_RATIO,
                     check_high5_breakout, calc_hard_stop, notify_telegram, send_long_message,
                     load_trade_history, save_trade_history, check_whipsaw)
from storage import load_positions, save_positions, gen_position_id, already_holding, load_watch, save_watch_for_market

MARKET_LABEL = 'US'
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


def is_us_market_open():
    now = datetime.now(ZoneInfo('America/New_York'))
    if now.weekday() >= 5:
        return False
    return dtime(9, 30) <= now.time() <= dtime(16, 0)


if __name__ == "__main__":
    if not is_us_market_open():
        print("미국 장 시간이 아니라서 재확인을 건너뜁니다 (평일 09:30~16:00 ET).")
        sys.exit(0)

    watch_df = load_watch()
    target_rows = watch_df[watch_df['market'] == MARKET_LABEL].to_dict('records')
    if not target_rows:
        print("현재 관심종목이 없습니다.")
        sys.exit(0)

    print(f"관심종목 {len(target_rows)}개 재확인 중...")
    tickers = list({r['code'] for r in target_rows})
    end = datetime.today()
    start = end - timedelta(days=120)

    data = yf.download(tickers, start=start, end=end, group_by='ticker',
                        auto_adjust=True, threads=True, progress=False)

    results = []
    for row in target_rows:
        code = row['code']
        try:
            df = data[code].dropna() if len(tickers) > 1 else data.dropna()
            if df.empty:
                continue
            res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
            if res:
                results.append({'code': code, 'name': row['name'], **res})
        except Exception:
            continue

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
                       'status': 'active', 'entry_date': end.strftime('%Y-%m-%d')}
            pos_df = pd.concat([pos_df, pd.DataFrame([new_pos])], ignore_index=True)
            entry_rows.append({**r, 'position_id': pid, 'hard_stop_price': hard_stop})
        elif r['watch_signal']:
            still_watch_rows.append(r)

    save_positions(pos_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    still_watch_df = pd.DataFrame(still_watch_rows)
    save_watch_for_market(MARKET_LABEL, still_watch_df)

    print(f"[미장 재확인] 신규진입 {len(entry_rows)}개 / 관심유지 {len(still_watch_df)}개 / "
          f"스킵(추격과다) {skip_chase}개 / 스킵(휩쏘) {skip_whipsaw}개")

    if entry_rows:
        lines = [f"[미장 5일신고가] 장중 돌파! 신규 진입 {len(entry_rows)}건 (포지션 자동 등록됨)"]
        for r in entry_rows:
            lines.append(
                f"- {r['name']} [거래번호 {r['position_id']}]\n"
                f"  진입가 {r['close']} / 5일고가 {r['n_high']}\n"
                f"  청산: 3일 신저가 이탈 시 / 하드스탑 {r['hard_stop_price']}"
            )
        send_long_message("\n".join(lines))
    else:
        print("[미장 재확인] 신규 전환 없음")
