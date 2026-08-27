# -*- coding: utf-8 -*-
"""미국 관심종목 재확인 (GitHub Actions에서 5분마다 자동 실행, 장중에만 동작)
⚠️ 알림만 하며, 실제 매수/매도는 텔레그램 buy/sell 명령으로만 이뤄짐."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from common import (MAX_CHASE_RATIO, check_high5_system, notify_telegram,
                     load_trade_history, save_trade_history, check_whipsaw, record_trade_result)
from storage import load_scan, save_scan_for_market

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

    scan_df = load_scan()
    prev_df = scan_df[scan_df['market'] == MARKET_LABEL].copy()
    target_rows = prev_df[prev_df['signal'].isin(['관심', '확정'])].to_dict('records')
    if not target_rows:
        print("현재 관심/확정 종목이 없습니다.")
        sys.exit(0)

    print(f"관심/확정 종목 {len(target_rows)}개 재확인 중...")
    tickers = list({r['code'] for r in target_rows})
    end = datetime.today()
    start = end - timedelta(days=120)

    data = yf.download(tickers, start=start, end=end, group_by='ticker',
                        auto_adjust=True, threads=True, progress=False)

    results = []
    for row in target_rows:
        code, name, orig_signal = row['code'], row['name'], row['signal']
        try:
            df = data[code].dropna() if len(tickers) > 1 else data.dropna()
            if df.empty:
                continue
            res = check_high5_system(df)
            if not res:
                continue

            if orig_signal == '확정':
                status = '확정이탈' if res['exit_signal'] else '확정유지'
            elif res['fresh_entry_signal']:
                chase_ratio = (res['close'] - res['n_high']) / res['n_high']
                status = '스킵(추격과다)' if chase_ratio > MAX_CHASE_RATIO else '확정_candidate'
            else:
                status = '유지' if res['watch_signal'] else '탈락'

            results.append({'code': code, 'name': name, 'status': status,
                             'entry_price': row.get('entry_price', ''), **res})
        except Exception:
            continue

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
    print(f"[미장 재확인] 확정 {len(confirm_df)}개 / 확정이탈 {len(exit_df)}개 / "
          f"휩쏘스킵 {whipsaw_skip_count}개 / 스킵(추격과다) {skip_cnt}개")

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

    save_scan_for_market(MARKET_LABEL, prev_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    if not confirm_df.empty:
        lines = [f"- {r['name']}\n"
                 f"  현재가 {r['close']} / 진입가(돌파) {r['n_high']} / 참고 3일저가 {r['n_low']}\n"
                 f"  괴리율 {(r['close']-r['n_high'])/r['n_high']*100:.2f}%\n"
                 f"  buy {r['code']} {r['close']} 명령으로 등록할 수 있어요."
                 for _, r in confirm_df.iterrows()]
        notify_telegram("[미장] 확정 전환 종목! (매수 검토)\n" + "\n".join(lines))

    if not exit_df.empty:
        lines = [f"- {r['name']}\n  현재가 {r['close']} / 3일저가(참고) {r['n_low']}"
                 for _, r in exit_df.iterrows()]
        notify_telegram("[미장] 확정이탈 종목! (보유 중이면 매도 검토)\n" + "\n".join(lines))
