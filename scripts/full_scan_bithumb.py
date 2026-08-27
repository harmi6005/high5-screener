# -*- coding: utf-8 -*-
"""빗썸 KRW 마켓 5일 신고가 전체 코인 스캔 (GitHub Actions에서 지정 시간에 자동 실행)

⚠️ 알림 전용입니다. 자동으로 매수하지 않습니다. 실제 매수는 텔레그램 `buy` 명령으로만
등록됩니다."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import MAX_CHASE_RATIO, check_high5_system, notify_telegram, send_long_message, build_watch_summary, pick_top_entry
from storage import save_scan_for_market

MAX_WORKERS = 10
MARKET_LABEL = 'COIN'


def get_bithumb_krw_coins():
    url = "https://api.bithumb.com/public/ticker/ALL_KRW"
    res = requests.get(url, timeout=10).json()
    data = res.get('data', {})
    return [k for k in data.keys() if k != 'date']


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

    return {'code': coin, 'name': coin, 'signal': signal, **res}


if __name__ == "__main__":
    print("[코인 5일신고가] KRW 마켓 코인 목록 불러오는 중...")
    coins = get_bithumb_krw_coins()
    print(f"총 {len(coins)}개 코인 병렬 조회 시작")

    rows = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_and_check, c): c for c in coins}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            if r:
                rows.append(r)
            if i % 50 == 0:
                print(f"  ...{i}/{len(coins)} 완료")

    df = pd.DataFrame(rows)
    save_scan_for_market(MARKET_LABEL, df)

    entry_cnt = len(df[df['signal'] == '진입']) if not df.empty else 0
    watch_cnt = len(df[df['signal'] == '관심']) if not df.empty else 0
    print(f"[코인 5일신고가] 진입 {entry_cnt}개 / 관심 {watch_cnt}개")

    if entry_cnt > 0:
        top = pick_top_entry(df)
        if top is not None:
            excess_pct = top['excess_ratio'] * 100
            msg = (
                f"[코인 전체스캔] 진입 신호 {entry_cnt}개 중 최신 돌파 1개 픽 (매수 검토)\n"
                f"- {top['name']}\n"
                f"  현재가 {top['close']} / 진입가(돌파) {top['n_high']} / 참고 3일저가 {top['n_low']}\n"
                f"  초과율 {excess_pct:.3f}%\n"
                f"buy {top['code']} {top['close']} 명령으로 등록할 수 있어요."
            )
            notify_telegram(msg)
    else:
        notify_telegram("[코인 5일신고가] 전체스캔 완료 - 신규 진입 없음")

    if watch_cnt > 0:
        summary = build_watch_summary(df[df['signal'] == '관심'], "코인 5일신고가")
        if summary:
            send_long_message(summary)
