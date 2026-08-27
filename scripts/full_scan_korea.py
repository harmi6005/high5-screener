# -*- coding: utf-8 -*-
"""국내(코스피) 5일 신고가 전체 스캔 (GitHub Actions에서 지정 시간에 자동 실행)
가격 필터 없이 코스피 전 종목을 대상으로 함.
신규 진입(fresh_entry_signal)이 뜨고 추격필터+휩쏘필터를 모두 통과하면
포지션을 자동 등록하고, 3일 신저가 채널청산 + 하이브리드 하드스탑으로 관리 시작."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import time
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (ENTRY_PERIOD, WATCH_RATIO, MAX_CHASE_RATIO,
                     check_high5_breakout, calc_hard_stop, notify_telegram, send_long_message,
                     build_watch_summary, load_trade_history, save_trade_history,
                     check_whipsaw)
from storage import load_positions, save_positions, gen_position_id, already_holding, save_watch_for_market

MAX_WORKERS = 20
MARKET_LABEL = 'KR'
KRX_MARKET = 'KOSPI'
# ⚠️ 가격 필터 없음 (필요 시 아래 두 상수를 채워서 필터링 가능)
PRICE_MIN = None
PRICE_MAX = None

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


def get_listing_with_retry(retries=3, wait_sec=15):
    for i in range(retries):
        try:
            listing = fdr.StockListing(KRX_MARKET)
            if listing is not None and not listing.empty:
                return listing
        except Exception as e:
            print(f"KRX 조회 실패({i+1}/{retries}): {e}")
        if i < retries - 1:
            time.sleep(wait_sec)
    return None


def fetch_and_check(code_name, start, end):
    code, name = code_name
    try:
        df = fdr.DataReader(code, start, end)
        if df.empty or len(df) < 60:
            return None
    except Exception:
        return None
    res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
    if not res:
        return None
    return {'code': code, 'name': name, **res}


if __name__ == "__main__":
    listing = get_listing_with_retry()
    if listing is None:
        notify_telegram("[국장 5일신고가] 스캔 실패 - KRX 종목리스트 조회 불가 (3회 재시도 후 포기)")
        sys.exit(0)

    if PRICE_MIN is not None and PRICE_MAX is not None and 'Close' in listing.columns:
        before_cnt = len(listing)
        listing = listing[(listing['Close'] >= PRICE_MIN) & (listing['Close'] <= PRICE_MAX)]
        print(f"가격 필터 적용: {before_cnt}개 -> {len(listing)}개")

    tickers = listing[['Code', 'Name']].values.tolist()
    print(f"총 {len(tickers)}개 종목 병렬 조회 시작")

    end = datetime.today()
    start = end - timedelta(days=120)

    raw_results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_check, cn, start, end): cn for cn in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            if r:
                raw_results.append(r)
            if i % 300 == 0:
                print(f"  ...{i}/{len(tickers)} 완료")

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
                continue  # 이미 보유 중인 종목은 중복 진입 안 함
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

    print(f"[국장 5일신고가] 진입 {len(entry_rows)}개 / 관심 {len(watch_df)}개 / "
          f"스킵(추격과다) {skip_chase}개 / 스킵(휩쏘) {skip_whipsaw}개")

    if entry_rows:
        lines = [f"[국장 5일신고가] 신규 진입 {len(entry_rows)}건 (포지션 자동 등록됨)"]
        for r in entry_rows:
            lines.append(
                f"- {r['name']}({r['code']}) [거래번호 {r['position_id']}]\n"
                f"  진입가 {r['close']} / 5일고가 {r['n_high']}\n"
                f"  청산: 3일 신저가 이탈 시 / 하드스탑 {r['hard_stop_price']}"
            )
        send_long_message("\n".join(lines))
    else:
        notify_telegram("[국장 5일신고가] 전체스캔 완료 - 신규 진입 없음")

    if not watch_df.empty:
        summary = build_watch_summary(watch_df, "국장 5일신고가")
        if summary:
            send_long_message(summary)
