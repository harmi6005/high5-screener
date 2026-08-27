# -*- coding: utf-8 -*-
"""positions.csv / watch.csv / tracked.csv 공용 로드-세이브 헬퍼.

- positions.csv / watch.csv: 자동매매 파이프라인 전용 (market 컬럼으로 국장/미장/코인 통합)
- tracked.csv: 텔레그램 `코드 추적시작` 명령으로 등록하는 수동 감시목록.
  자동 진입/청산 파이프라인과는 완전히 별개이며, `추적확인` 명령으로 실시간 재조회만 함
  (터틀 스크리너의 watchlist.csv/추적시작·추적종료·추적확인과 동일한 역할).
"""

import os
import random
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
POSITIONS_PATH = os.path.join(DATA_DIR, 'positions.csv')
WATCH_PATH = os.path.join(DATA_DIR, 'watch.csv')
TRACKED_PATH = os.path.join(DATA_DIR, 'tracked.csv')

# hard_stop_price: 진입 시점에 고정되는 하이브리드 하드스탑 (트레일링 안 함)
# highest_price: 정보성 최고가 기록 (마일스톤 진행상황 알림용, 손절과 무관)
# last_n_low: 직전 체크 시점의 3일저가선(청산가) 값, 추세 표시용
POSITIONS_COLUMNS = ['position_id', 'market', 'code', 'name', 'entry_price', 'atr_entry',
                     'hard_stop_price', 'highest_price', 'last_milestone', 'last_price',
                     'last_n_low', 'status', 'entry_date']
# last_close: 직전 체크 시점의 현재가, 추세 표시용 (watchlist_check.py 전용)
WATCH_COLUMNS = ['market', 'code', 'name', 'close', 'n_high', 'n_high_ratio', 'atr', 'last_close']
TRACKED_COLUMNS = ['market', 'code', 'name']


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
    if pos_df.empty:
        return False
    return ((pos_df['market'] == market) & (pos_df['code'] == code) &
            (pos_df['status'] == 'active')).any()


def load_watch():
    if os.path.exists(WATCH_PATH):
        df = pd.read_csv(WATCH_PATH, dtype={'code': str, 'market': str})
        for col in WATCH_COLUMNS:
            if col not in df.columns:
                df[col] = ''
        return df[WATCH_COLUMNS]
    return pd.DataFrame(columns=WATCH_COLUMNS)


def save_watch_for_market(market, new_rows_df):
    """watch.csv에서 해당 market 행만 지우고 새 데이터로 교체 (다른 시장 데이터 보존).
    같은 코드가 기존에도 있었다면 last_close를 이어받아서(carry-forward) 추세 표시가
    끊기지 않게 하고, 새로 잡힌 코드는 last_close를 비워둬서 다음 체크 때 🆕로 표시되게 함."""
    existing = load_watch()
    old_market_rows = existing[existing['market'] == market]
    old_last_close_map = dict(zip(old_market_rows['code'], old_market_rows['last_close']))
    existing = existing[existing['market'] != market]

    if new_rows_df is None or new_rows_df.empty:
        combined = existing
    else:
        new_rows_df = new_rows_df.copy()
        new_rows_df['market'] = market
        if 'last_close' not in new_rows_df.columns:
            new_rows_df['last_close'] = ''
        new_rows_df['last_close'] = new_rows_df.apply(
            lambda r: old_last_close_map.get(r['code'], ''), axis=1)
        combined = pd.concat([existing, new_rows_df[WATCH_COLUMNS]], ignore_index=True)

    os.makedirs(DATA_DIR, exist_ok=True)
    combined.to_csv(WATCH_PATH, index=False, encoding='utf-8-sig')
    return combined


def save_watch_full(df):
    """watch.csv 전체를 그대로 덮어쓴다 (행 추가/삭제 없이 필드 값만 갱신할 때 사용,
    예: watchlist_check.py가 현재가/last_close를 갱신할 때)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(WATCH_PATH, index=False, encoding='utf-8-sig')


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
