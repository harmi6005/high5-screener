# -*- coding: utf-8 -*-
"""자동스캔 관심종목(scan.csv, signal=='관심') 5분마다 무조건 현황 요약
(GitHub Actions에서 5분마다 자동 실행)

⚠️ 알림 전용입니다. 여기서 조회하는 관심종목은 recheck_*.py가 '확정'으로
승격시키는 것과 별개로, 순수하게 현재 상태를 보여주기만 함."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
import pandas as pd
import FinanceDataReader as fdr
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from common import fmt_num, trend_arrow, send_long_message
from storage import load_scan, save_scan_full

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
        return "⚡ 돌파(재확인 대기)"
    if ratio >= 0.99:
        return "🔶 돌파임박"
    return "🟢 관찰중"


if __name__ == "__main__":
    scan_df = load_scan()
    watch_df = scan_df[scan_df['signal'] == '관심'].copy()
    if watch_df.empty:
        print("현재 관심종목이 없습니다.")
        sys.exit(0)

    for col in ['close', 'n_high', 'n_high_ratio', 'last_close']:
        watch_df[col] = pd.to_numeric(watch_df[col], errors='coerce')

    kr_open = is_korea_market_open()
    us_open = is_us_market_open()

    us_codes = watch_df[watch_df['market'] == 'US']['code'].unique().tolist()
    us_prices = get_us_prices(us_codes) if (us_codes and us_open) else {}

    changed = False
    summary_rows = []

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
        arrow = trend_arrow(price, row['last_close'])
        tag = build_tag(ratio)
        ratio_str = f"{ratio*100:.1f}%" if ratio is not None else "N/A"

        summary_rows.append(
            f"- {row['name']}({code}) [{market}] {tag}\n"
            f"  현재가 {fmt_num(price)} {arrow} / 5일고가선 {fmt_num(n_high)} ({ratio_str})"
        )

        scan_idx = scan_df[(scan_df['market'] == market) & (scan_df['code'] == code)].index
        scan_df.loc[scan_idx, 'last_close'] = float(price)
        scan_df.loc[scan_idx, 'close'] = float(price)
        changed = True

    if changed:
        save_scan_full(scan_df)

    if summary_rows:
        header = f"🎯 [관심종목 현황] {len(summary_rows)}종목 (5분 자동 갱신, 알림 전용)"
        send_long_message(header + "\n" + "\n".join(summary_rows))
    else:
        print("이번 회차에 체크된(장중/코인) 관심종목이 없어 요약을 생략합니다.")
