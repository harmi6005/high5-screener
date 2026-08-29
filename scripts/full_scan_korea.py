# -*- coding: utf-8 -*-
"""국내(코스피) 5일 신고가 전체 스캔 (GitHub Actions에서 지정 시간에 자동 실행)

⚠️ 알림 전용입니다. 자동으로 매수하지 않습니다. 실제 매수는 텔레그램 `buy` 명령으로만
등록됩니다 (터틀 스크리너와 동일한 방식). 이 스크립트는 scan.csv에 신호 상태만 기록함.

진입 신호가 여러 개 뜨면, 돌파 강도(ATR 대비 5일 신고가 초과폭)가 가장 큰 상위
TOP_PICKS_COUNT(기본 3)개를 골라 "강력한 픽" 알림으로 발송한다."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import time
import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (MAX_CHASE_RATIO, TOP_PICKS_COUNT, check_high5_system, notify_telegram,
                     send_long_message, build_watch_summary, pick_top_entries)
from storage import save_scan_for_market

MAX_WORKERS = 20
MARKET_LABEL = 'KR'
KRX_MARKET = 'KOSPI'
# ⚠️ 가격 필터 없음 (필요 시 아래 두 상수를 채워서 필터링 가능)
PRICE_MIN = None
PRICE_MAX = None


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

    res = check_high5_system(df)
    if not res:
        return None

    if res['fresh_entry_signal']:
        chase_ratio = (res['close'] - res['n_high']) / res['n_high']
        if chase_ratio > MAX_CHASE_RATIO:
            return None  # 이미 너무 많이 오른 상태 -> 후보에서 제외
        signal = '진입'
    elif res['exit_signal']:
        signal = '청산'
    elif res['watch_signal']:
        signal = '관심'
    else:
        return None

    return {'code': code, 'name': name, 'signal': signal, 'entry_price': '', **res}


def build_top_picks_message(top_entries, entry_cnt):
    lines = [f"[국장 전체스캔] 진입 신호 {entry_cnt}개 중 강도 상위 {len(top_entries)}개 픽 (매수 검토)"]
    for rank, (_, row) in enumerate(top_entries.iterrows(), 1):
        lines.append(
            f"{rank}위. {row['name']}({row['code']})\n"
            f"   현재가 {row['close']} / 진입가(5일 신고가) {row['n_high']} / 참고 3일저가 {row['n_low']}\n"
            f"   강도(ATR배수) {row['strength']:.3f} / 초과율 {row['excess_ratio']*100:.3f}%\n"
            f"   buy {row['code']} {row['close']} 명령으로 등록할 수 있어요."
        )
    return "\n".join(lines)


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

    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_check, cn, start, end): cn for cn in tickers}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            if r:
                rows.append(r)
            if i % 300 == 0:
                print(f"  ...{i}/{len(tickers)} 완료")

    df = pd.DataFrame(rows)
    save_scan_for_market(MARKET_LABEL, df)

    entry_cnt = len(df[df['signal'] == '진입']) if not df.empty else 0
    watch_cnt = len(df[df['signal'] == '관심']) if not df.empty else 0
    print(f"[국장 5일신고가] 진입 {entry_cnt}개 / 관심 {watch_cnt}개")

    if entry_cnt > 0:
        top_entries = pick_top_entries(df, top_n=TOP_PICKS_COUNT)
        if not top_entries.empty:
            send_long_message(build_top_picks_message(top_entries, entry_cnt))
    else:
        notify_telegram("[국장 5일신고가] 전체스캔 완료 - 신규 진입 없음")

    if watch_cnt > 0:
        summary = build_watch_summary(df[df['signal'] == '관심'], "국장 5일신고가")
        if summary:
            send_long_message(summary)
