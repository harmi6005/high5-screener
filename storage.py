# -*- coding: utf-8 -*-
"""세 가지 완전히 분리된 데이터를 각각 관리하는 저장소 헬퍼 (터틀 스크리너와 동일한 3분할 구조).

1. scan.csv    : 자동 전체스캔/재확인 파이프라인 전용 신호 캐시. 알림만 하고 실제 매수는
                 절대 안 함 (터틀의 turtle_korea_result.csv 등에 대응). signal 값:
                 진입/관심/확정/확정이탈/탈락.
2. positions.csv : 텔레그램 `buy` 명령으로만 생기는 실제 보유종목 (터틀의 holdings.csv에
                 대응). scan.csv와는 완전히 무관 — 자동스캔이 '진입'을 찾아도 여기에
                 아무것도 안 씀. status 값: active/stop_hit/closed_manual.
3. tracked.csv : 텔레그램 `코드 추적시작`으로 등록하는 수동 감시목록 (터틀의
                 watchlist.csv에 대응). 위 둘과도 무관.
"""

import os
import random
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
SCAN_PATH = os.path.join(DATA_DIR, 'scan.csv')
POSITIONS_PATH = os.path.join(DATA_DIR, 'positions.csv')
TRACKED_PATH = os.path.join(DATA_DIR, 'tracked.csv')

# ===== 1. 자동스캔 신호 캐시 (scan.csv) =====
# signal: 진입 / 관심 / 확정 / 확정이탈 / 탈락
# entry_price: '확정' 전환 시점의 종가 (확정이탈 때 휩쏘 이력 기록에 사용)
# last_close: watchlist_check.py가 5분마다 갱신하는 직전 현재가 (추세 표시용)
SCAN_COLUMNS = ['market', 'code', 'name', 'signal', 'entry_price',
                'close', 'high', 'n_high', 'n_high_ratio', 'atr', 'low', 'n_low', 'last_close']


def load_scan():
    if os.path.exists(SCAN_PATH):
        df = pd.read_csv(SCAN_PATH, dtype={'code': str, 'market': str})
        for col in SCAN_COLUMNS:
            if col not in df.columns:
                df[col] = ''
        return df[SCAN_COLUMNS]
    return pd.DataFrame(columns=SCAN_COLUMNS)


def save_scan_for_market(market, new_rows_df):
    """scan.csv에서 해당 market 행만 지우고 새 데이터로 교체.
    단, 기존에 '확정' 상태였던 코드가 이번 스캔 결과에 없으면(재확인이 계속 감시해야
    하므로) 보존한다 — 터틀 full_scan이 확정 종목을 덮어쓰지 않는 것과 동일 로직.
    또한 last_close는 코드가 같으면 이어받아서(carry-forward) 추세표시가 안 끊기게 함."""
    existing = load_scan()
    old_market_rows = existing[existing['market'] == market]
    old_last_close_map = dict(zip(old_market_rows['code'], old_market_rows['last_close']))
    confirmed_prev = old_market_rows[old_market_rows['signal'] == '확정']

    other_market_rows = existing[existing['market'] != market]

    if new_rows_df is None or new_rows_df.empty:
        new_rows_df = pd.DataFrame(columns=SCAN_COLUMNS)
    else:
        new_rows_df = new_rows_df.copy()
        new_rows_df['market'] = market

    if not confirmed_prev.empty:
        new_codes = set(new_rows_df['code']) if not new_rows_df.empty else set()
        keep_confirmed = confirmed_prev[~confirmed_prev['code'].isin(new_codes)]
        if not keep_confirmed.empty:
            new_rows_df = pd.concat([new_rows_df, keep_confirmed], ignore_index=True)

    if 'last_close' not in new_rows_df.columns:
        new_rows_df['last_close'] = ''
    new_rows_df['last_close'] = new_rows_df.apply(
        lambda r: old_last_close_map.get(r['code'], r.get('last_close', '')), axis=1)

    combined = pd.concat([other_market_rows, new_rows_df[SCAN_COLUMNS]], ignore_index=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    combined.to_csv(SCAN_PATH, index=False, encoding='utf-8-sig')
    return combined


def save_scan_full(df):
    """scan.csv 전체를 그대로 덮어쓴다 (행 추가/삭제 없이 필드 값만 갱신할 때,
    예: watchlist_check.py가 현재가/last_close만 갱신할 때)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(SCAN_PATH, index=False, encoding='utf-8-sig')


# ===== 2. 실제 보유종목 (positions.csv, buy 명령으로만 생성) =====
POSITIONS_COLUMNS = ['position_id', 'market', 'code', 'name', 'entry_price', 'atr_entry',
                     'hard_stop_price', 'highest_price', 'last_milestone', 'last_price',
                     'last_n_low', 'status', 'entry_date']


def load_positions():
    if os.path.exists(POSITIONS_PATH):
        df = pd.read_csv(POSITIONS_PATH, dtype={'code': str, 'position_id': str, 'market': str})
        for col in POSITIONS_COLUMNS:
            if col not in df.columns:
                df[col] = ''
        return df[POSITIONS_COLUMNS]
    return pd.DataFrame(columns=POSITIONS_COLUMNS)


def save_positions(df):
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(POSITIONS_PATH, index=False, encoding='utf-8-sig')


def gen_position_id(df):
    existing = set(df['position_id'].astype(str)) if not df.empty else set()
    while True:
        pid = f"{random.randint(0, 9999):04d}"
        if pid not in existing:
            return pid


def already_holding(pos_df, market, code):
    """status가 closed_manual이 아닌(active 또는 stop_hit) 동일 종목이 있으면 True.
    stop_hit도 '아직 안 판' 상태라 중복 buy를 막아야 함 (터틀과 동일)."""
    if pos_df.empty:
        return False
    return ((pos_df['market'] == market) & (pos_df['code'] == code) &
            (pos_df['status'] != 'closed_manual')).any()


# ===== 3. 수동 추적목록 (tracked.csv) =====
TRACKED_COLUMNS = ['code', 'market', 'status']


def load_tracked():
    if os.path.exists(TRACKED_PATH):
        df = pd.read_csv(TRACKED_PATH, dtype={'code': str, 'market': str})
        for col in TRACKED_COLUMNS:
            if col not in df.columns:
                df[col] = ''
        return df[TRACKED_COLUMNS]
    return pd.DataFrame(columns=TRACKED_COLUMNS)


def save_tracked(df):
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(TRACKED_PATH, index=False, encoding='utf-8-sig')
