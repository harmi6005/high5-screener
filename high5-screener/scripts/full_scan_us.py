# -*- coding: utf-8 -*-
"""미국 주식(S&P500) 5일 신고가 전체 스캔 (GitHub Actions에서 지정 시간에 자동 실행)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from common import (ENTRY_PERIOD, WATCH_RATIO, MAX_CHASE_RATIO,
                     check_high5_breakout, calc_hard_stop, notify_telegram, send_long_message,
                     build_watch_summary, load_trade_history, save_trade_history,
                     check_whipsaw)
from storage import load_positions, save_positions, gen_position_id, already_holding, save_watch_for_market

MARKET_LABEL = 'US'
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


def get_sp500_tickers():
    url = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'
    df = pd.read_csv(url)
    return df['Symbol'].str.replace('.', '-', regex=False).tolist()


if __name__ == "__main__":
    print("[미장 5일신고가] S&P500 종목 리스트 불러오는 중...")
    tickers = get_sp500_tickers()
    print(f"총 {len(tickers)}개 종목 배치 다운로드 중...")

    end = datetime.today()
    start = end - timedelta(days=120)

    data = yf.download(tickers, start=start, end=end, group_by='ticker',
                        auto_adjust=True, threads=True, progress=False)

    raw_results = []
    for t in tickers:
        try:
            df = data[t].dropna()
            if df.empty or len(df) < 60:
                continue
            res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
            if res:
                raw_results.append({'code': t, 'name': t, **res})
        except Exception:
            continue

    pos_df = load_positions()
    hist_df = load_trade_history(HIST_PATH)
    hist_changed = False

    entry_rows = []
    watch_rows = []
    skip_chase = 0
    skip_whipsaw = 0

    for r in raw_results:
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
            watch_rows.append(r)

    save_positions(pos_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    watch_df = pd.DataFrame(watch_rows)
    save_watch_for_market(MARKET_LABEL, watch_df)

    print(f"[미장 5일신고가] 진입 {len(entry_rows)}개 / 관심 {len(watch_df)}개 / "
          f"스킵(추격과다) {skip_chase}개 / 스킵(휩쏘) {skip_whipsaw}개")

    if entry_rows:
        lines = [f"[미장 5일신고가] 신규 진입 {len(entry_rows)}건 (포지션 자동 등록됨)"]
        for r in entry_rows:
            lines.append(
                f"- {r['name']} [거래번호 {r['position_id']}]\n"
                f"  진입가 {r['close']} / 5일고가 {r['n_high']}\n"
                f"  청산: 3일 신저가 이탈 시 / 하드스탑 {r['hard_stop_price']}"
            )
        send_long_message("\n".join(lines))
    else:
        notify_telegram("[미장 5일신고가] 전체스캔 완료 - 신규 진입 없음")

    if not watch_df.empty:
        summary = build_watch_summary(watch_df, "미장 5일신고가")
        if summary:
            send_long_message(summary)
