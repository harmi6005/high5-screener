# -*- coding: utf-8 -*-
"""빗썸 KRW 마켓 5일 신고가 스캔 (GitHub Actions에서 지정 시간에 자동 실행)

⚠️ 알림 전용입니다. 자동으로 매수하지 않습니다. 실제 매수는 텔레그램 `buy` 명령으로만
등록됩니다.

⚠️ 코인은 국장/미장과 달리 "빗썸 KRW 전체 코인"을 스캔하지 않는다. 대신 텔레그램
`코드 추적시작` 명령으로 사용자가 직접 등록한(관심등록한) 코인, 즉 tracked.csv에서
market='COIN'인 종목만 스캔 대상으로 삼는다. (사용자 요청: "코인은 내가 관심등록한
종목만 알림받도록" — 전체 코인 알림이 너무 잦아서 범위를 사용자가 고른 코인으로 좁힘)

관심등록된 코인이 하나도 없으면 이 스크립트는 조용히 아무 것도 하지 않는다.

진입 신호가 여러 개 뜨면, 돌파 강도(ATR 대비 5일 신고가 초과폭)가 가장 큰 상위
TOP_PICKS_COUNT(기본 3)개를 골라 "강력한 픽" 알림으로 발송한다."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (MAX_CHASE_RATIO, TOP_PICKS_COUNT, check_high5_system, notify_telegram,
                     send_long_message, build_watch_summary, pick_top_entries)
from storage import save_scan_for_market, load_tracked

MAX_WORKERS = 10
MARKET_LABEL = 'COIN'


def get_registered_coins():
    """tracked.csv에서 market='COIN'으로 관심등록된 코인 티커 목록만 반환.
    (전체 빗썸 KRW 코인이 아니라 사용자가 `코드 추적시작`으로 직접 등록한 것만)"""
    tracked_df = load_tracked()
    if tracked_df.empty:
        return []
    coin_rows = tracked_df[tracked_df['market'] == 'COIN']
    return coin_rows['code'].dropna().unique().tolist()


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


def fetch_and_check(coin):
    try:
        df = get_bithumb_daily_ohlc(coin)
        if df is None or df.empty or len(df) < 60:
            return None
    except Exception:
        return None

    res = check_high5_system(df)
    if not res:
        return None

    if res['fresh_entry_signal']:
        chase_ratio = (res['close'] - res['n_high']) / res['n_high']
        if chase_ratio > MAX_CHASE_RATIO:
            return None
        signal = '진입'
    elif res['exit_signal']:
        signal = '청산'
    elif res['watch_signal']:
        signal = '관심'
    else:
        return None

    return {'code': coin, 'name': coin, 'signal': signal, 'entry_price': '', **res}


def build_top_picks_message(top_entries, entry_cnt):
    lines = [f"[코인 관심등록 스캔] 진입 신호 {entry_cnt}개 중 강도 상위 {len(top_entries)}개 픽 (매수 검토)"]
    for rank, (_, row) in enumerate(top_entries.iterrows(), 1):
        lines.append(
            f"{rank}위. {row['name']}\n"
            f"   현재가 {row['close']} / 진입가(5일 신고가) {row['n_high']} / 참고 3일저가 {row['n_low']}\n"
            f"   강도(ATR배수) {row['strength']:.3f} / 초과율 {row['excess_ratio']*100:.3f}%\n"
            f"   buy {row['code']} {row['close']} 명령으로 등록할 수 있어요."
        )
    return "\n".join(lines)


if __name__ == "__main__":
    coins = get_registered_coins()
    if not coins:
        print("[코인 5일신고가] 관심등록된 코인이 없어 스캔을 건너뜁니다. "
              "'코드 추적시작' 명령으로 먼저 코인을 등록하세요.")
        sys.exit(0)

    print(f"관심등록된 코인 {len(coins)}개 조회 시작: {coins}")

    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_check, c): c for c in coins}
        for future in as_completed(futures):
            r = future.result()
            if r:
                rows.append(r)

    df = pd.DataFrame(rows)
    save_scan_for_market(MARKET_LABEL, df)

    entry_cnt = len(df[df['signal'] == '진입']) if not df.empty else 0
    watch_cnt = len(df[df['signal'] == '관심']) if not df.empty else 0
    print(f"[코인 5일신고가] 진입 {entry_cnt}개 / 관심 {watch_cnt}개 (관심등록 {len(coins)}개 중)")

    if entry_cnt > 0:
        top_entries = pick_top_entries(df, top_n=TOP_PICKS_COUNT)
        if not top_entries.empty:
            send_long_message(build_top_picks_message(top_entries, entry_cnt))
    else:
        notify_telegram(f"[코인 5일신고가] 관심등록 {len(coins)}개 스캔 완료 - 신규 진입 없음")

    if watch_cnt > 0:
        summary = build_watch_summary(df[df['signal'] == '관심'], "코인 5일신고가(관심등록)")
        if summary:
            send_long_message(summary)
