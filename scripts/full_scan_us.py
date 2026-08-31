# -*- coding: utf-8 -*-
"""미국 주식(S&P500) 5일 신고가 전체 스캔 (GitHub Actions에서 지정 시간에 자동 실행)

⚠️ 알림 전용입니다. 자동으로 매수하지 않습니다. 실제 매수는 텔레그램 `buy` 명령으로만
등록됩니다.

진입 신호가 여러 개 뜨면, 돌파 강도(ATR 대비 5일 신고가 초과폭)가 가장 큰 상위
TOP_PICKS_COUNT(기본 3)개를 골라 "강력한 픽" 알림으로 발송한다."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from common import (MAX_CHASE_RATIO, TOP_PICKS_COUNT, check_high5_system, notify_telegram,
                     send_long_message, build_watch_summary, pick_top_entries)
from storage import save_scan_for_market, is_market_paused

MARKET_LABEL = 'US'


def get_sp500_tickers():
    url = 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv'
    df = pd.read_csv(url)
    return df['Symbol'].str.replace('.', '-', regex=False).tolist()


def build_top_picks_message(top_entries, entry_cnt):
    lines = [f"[미장 전체스캔] 진입 신호 {entry_cnt}개 중 강도 상위 {len(top_entries)}개 픽 (매수 검토)"]
    for rank, (_, row) in enumerate(top_entries.iterrows(), 1):
        lines.append(
            f"{rank}위. {row['name']}\n"
            f"   현재가 {row['close']} / 진입가(5일 신고가) {row['n_high']} / 참고 3일저가 {row['n_low']}\n"
            f"   강도(ATR배수) {row['strength']:.3f} / 초과율 {row['excess_ratio']*100:.3f}%\n"
            f"   buy {row['code']} {row['close']} 명령으로 등록할 수 있어요."
        )
    return "\n".join(lines)


if __name__ == "__main__":
    if is_market_paused('US'):
        print("미장 추적이 일시정지 상태라서 전체스캔을 건너뜁니다. "
              "'미장 추적재시작' 명령으로 재개할 수 있어요.")
        sys.exit(0)

    print("[미장 5일신고가] S&P500 종목 리스트 불러오는 중...")
    tickers = get_sp500_tickers()
    print(f"총 {len(tickers)}개 종목 배치 다운로드 중...")

    end = datetime.today()
    start = end - timedelta(days=120)

    data = yf.download(tickers, start=start, end=end, group_by='ticker',
                        auto_adjust=True, threads=True, progress=False)

    rows = []
    for t in tickers:
        try:
            df = data[t].dropna()
            if df.empty or len(df) < 60:
                continue
            res = check_high5_system(df)
            if not res:
                continue
            if res['fresh_entry_signal']:
                chase_ratio = (res['close'] - res['n_high']) / res['n_high']
                if chase_ratio > MAX_CHASE_RATIO:
                    continue
                signal = '진입'
            elif res['exit_signal']:
                signal = '청산'
            elif res['watch_signal']:
                signal = '관심'
            else:
                continue
            rows.append({'code': t, 'name': t, 'signal': signal, 'entry_price': '', **res})
        except Exception:
            continue

    df = pd.DataFrame(rows)
    save_scan_for_market(MARKET_LABEL, df)

    entry_cnt = len(df[df['signal'] == '진입']) if not df.empty else 0
    watch_cnt = len(df[df['signal'] == '관심']) if not df.empty else 0
    print(f"[미장 5일신고가] 진입 {entry_cnt}개 / 관심 {watch_cnt}개")

    if entry_cnt > 0:
        top_entries = pick_top_entries(df, top_n=TOP_PICKS_COUNT)
        if not top_entries.empty:
            send_long_message(build_top_picks_message(top_entries, entry_cnt))
    else:
        notify_telegram("[미장 5일신고가] 전체스캔 완료 - 신규 진입 없음")

    if watch_cnt > 0:
        summary = build_watch_summary(df[df['signal'] == '관심'], "미장 5일신고가")
        if summary:
            send_long_message(summary)
