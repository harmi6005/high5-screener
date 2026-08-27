# -*- coding: utf-8 -*-
"""추적목록(tracked.csv) 전용 5일신고가/3일신저가 신호 체크 (GitHub Actions에서 5분마다 자동 실행)

터틀 스크리너의 watchlist_check.py를 응용. 텔레그램 `코드 추적시작` 명령으로
등록한 종목들의 상태(진입/청산/관심/관찰중)를 체크해서, **직전 상태와 다를 때만**
알림을 보낸다 (상태 변화가 없으면 조용함 — position_check.py/watchlist_check.py의
"5분마다 무조건 요약"과는 다른 성격의 알림).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import ATR_PERIOD, ENTRY_PERIOD, EXIT_PERIOD, WATCH_RATIO
from common import check_high5_breakout, check_channel_exit, fetch_ohlc, fmt_num, notify_telegram
from storage import load_tracked, save_tracked

MIN_LEN = ENTRY_PERIOD * 2 + ATR_PERIOD + 5


def resolve_status(res, channel):
    if res['entry_signal']:
        return '진입'
    if channel and channel['exit_signal']:
        return '청산'
    if res['watch_signal']:
        return '관심'
    return '관찰중'


if __name__ == "__main__":
    tracked_df = load_tracked()
    if tracked_df.empty:
        print("현재 추적 중인 종목이 없습니다.")
        sys.exit(0)

    changed = False

    for idx, row in tracked_df.iterrows():
        code, market = row['code'], row['market']
        df = fetch_ohlc(market, code, days=60)
        if df is None or len(df) < MIN_LEN:
            print(f"- {code} [{market}]: 데이터 조회 실패/부족, 이번 회차 건너뜀")
            continue

        res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
        if not res:
            continue
        channel = check_channel_exit(df, EXIT_PERIOD)
        new_status = resolve_status(res, channel)
        old_status = row['status'] if row['status'] else None

        if new_status != old_status:
            gap_pct = (res['close'] - res['n_high']) / res['n_high'] * 100
            n_low_str = fmt_num(channel['n_low']) if channel else "N/A"
            notify_telegram(
                f"[추적목록] {code} [{market}] 상태 변화: "
                f"{old_status or '(초기)'} → {new_status}\n"
                f"현재가 {res['close']} / 5일고가 {res['n_high']} ({gap_pct:+.2f}%) / 3일저가 {n_low_str}"
            )
            tracked_df.at[idx, 'status'] = new_status
            changed = True
            print(f"- {code} [{market}]: {old_status} → {new_status} (알림 발송)")
        else:
            print(f"- {code} [{market}]: 상태 변화 없음 ({new_status})")

    if changed:
        save_tracked(tracked_df)
