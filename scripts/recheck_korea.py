# -*- coding: utf-8 -*-
"""국내 관심종목 재확인 (GitHub Actions에서 5분마다 자동 실행, 장중에만 동작)

5일신고가 돌파가 재확인(장중 재조회)에서도 유지되면 '확정'으로 승격 — 이때
휩쏘 필터(직전 거래가 수익이었으면 스킵)가 적용됨. '확정' 상태였던 종목이
3일 신저가를 이탈하면 '확정이탈'로 전환하고 휩쏘 학습용 이력에 기록.
⚠️ 여전히 알림만 하며, 실제 매수/매도는 텔레그램 buy/sell 명령으로만 이뤄짐.

⚠️ 기존에는 이 재확인과 별개로 watchlist_check.py가 5분마다 관심종목 시세를
"또" 조회해서 현황요약을 보냈는데, 같은 종목을 이중으로 조회하는 비효율이 있었음.
이번 수정으로 watchlist_check.py는 폐기하고, 이 스크립트가 이미 재확인 과정에서
가져온 시세(res)를 그대로 재사용해서 '관심' 상태로 남은 종목의 현황요약까지
같이 보내도록 통합함 (API 호출/실행시간 중복 제거)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pandas as pd
import FinanceDataReader as fdr
from datetime import datetime, timedelta, time as dtime
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import (MAX_CHASE_RATIO, check_high5_system, notify_telegram, send_long_message,
                     fmt_num, trend_arrow, load_trade_history, save_trade_history,
                     check_whipsaw, record_trade_result)
from storage import load_scan, save_scan_for_market

MAX_WORKERS = 20
MARKET_LABEL = 'KR'
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


def is_korea_market_open():
    now = datetime.now(ZoneInfo('Asia/Seoul'))
    if now.weekday() >= 5:
        return False
    return dtime(9, 0) <= now.time() <= dtime(15, 30)


def recheck_one(row, start, end):
    code, name, orig_signal = row['code'], row['name'], row['signal']
    try:
        df = fdr.DataReader(str(code).zfill(6), start, end)
        if df.empty:
            return None
        res = check_high5_system(df)
        if not res:
            return None

        if orig_signal == '확정':
            status = '확정이탈' if res['exit_signal'] else '확정유지'
        elif res['fresh_entry_signal']:
            chase_ratio = (res['close'] - res['n_high']) / res['n_high']
            status = '스킵(추격과다)' if chase_ratio > MAX_CHASE_RATIO else '확정_candidate'
        else:
            status = '유지' if res['watch_signal'] else '탈락'

        return {'code': code, 'name': name, 'status': status,
                'entry_price': row.get('entry_price', ''), **res}
    except Exception:
        return None


def build_watch_tag(ratio):
    if ratio is None or pd.isna(ratio):
        return "❔ 데이터부족"
    return "🔶 돌파임박" if ratio >= 0.99 else "🟢 관찰중"


if __name__ == "__main__":
    if not is_korea_market_open():
        print("국내 장 시간이 아니라서 재확인을 건너뜁니다 (평일 09:00~15:30 KST).")
        sys.exit(0)

    scan_df = load_scan()
    prev_df = scan_df[scan_df['market'] == MARKET_LABEL].copy()
    for col in ['close', 'n_high', 'n_high_ratio', 'last_close']:
        if col in prev_df.columns:
            prev_df[col] = pd.to_numeric(prev_df[col], errors='coerce')

    target_rows = prev_df[prev_df['signal'].isin(['관심', '확정'])].to_dict('records')
    if not target_rows:
        print("현재 관심/확정 종목이 없습니다.")
        sys.exit(0)

    print(f"관심/확정 종목 {len(target_rows)}개 재확인 중...")
    end = datetime.today()
    start = end - timedelta(days=120)

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(recheck_one, row, start, end): row for row in target_rows}
        for future in as_completed(futures):
            r = future.result()
            if r:
                results.append(r)

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
    print(f"[국장 재확인] 확정 {len(confirm_df)}개 / 확정이탈 {len(exit_df)}개 / "
          f"휩쏘스킵 {whipsaw_skip_count}개 / 스킵(추격과다) {skip_cnt}개")

    watch_lines = []
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
        elif status == '유지':
            # 여전히 '관심'으로 남은 종목 -> 재확인 때 이미 조회한 시세(res)를 그대로
            # 재사용해서 현황요약 한 줄을 만든다 (watchlist_check.py가 하던 별도
            # 시세 재조회를 없애기 위함).
            old_last_close = prev_df.loc[mask, 'last_close']
            old_val = float(old_last_close.iloc[0]) if not old_last_close.empty and pd.notna(old_last_close.iloc[0]) else None
            arrow = trend_arrow(r['close'], old_val)
            ratio = r.get('n_high_ratio')
            tag = build_watch_tag(ratio)
            ratio_str = f"{ratio*100:.1f}%" if ratio is not None and not pd.isna(ratio) else "N/A"
            watch_lines.append(
                f"- {r['name']}({code}) [KR] {tag}\n"
                f"  현재가 {fmt_num(r['close'])} {arrow} / 5일고가선 {fmt_num(r['n_high'])} ({ratio_str})"
            )
            prev_df.loc[mask, 'last_close'] = r['close']
            prev_df.loc[mask, 'close'] = r['close']

    save_scan_for_market(MARKET_LABEL, prev_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    if not confirm_df.empty:
        lines = [f"- {r['name']}({r['code']})\n"
                 f"  현재가 {r['close']} / 진입가(돌파) {r['n_high']} / 참고 3일저가 {r['n_low']}\n"
                 f"  괴리율 {(r['close']-r['n_high'])/r['n_high']*100:.2f}%\n"
                 f"  buy {r['code']} {r['close']} 명령으로 등록할 수 있어요."
                 for _, r in confirm_df.iterrows()]
        notify_telegram("[국장] 확정 전환 종목! (매수 검토)\n" + "\n".join(lines))

    if not exit_df.empty:
        lines = [f"- {r['name']}({r['code']})\n  현재가 {r['close']} / 3일저가(참고) {r['n_low']}"
                 for _, r in exit_df.iterrows()]
        notify_telegram("[국장] 확정이탈 종목! (보유 중이면 매도 검토)\n" + "\n".join(lines))

    if watch_lines:
        header = f"🎯 [관심종목 현황-국장] {len(watch_lines)}종목 (재확인과 통합, 알림 전용)"
        send_long_message(header + "\n" + "\n".join(watch_lines))
