# -*- coding: utf-8 -*-
"""5일 신고가 / 3일 신저가 자동매매 스크리너 공통 로직 (모든 스크립트가 공유)

터틀 스크리너(turtle-screener)와 별도의 봇/저장소로 운영됨.

- 진입: 최근 5거래일 동안 한 번도 못 넘던 5일 최고가를 오늘 처음 종가로 돌파 (fresh_entry_signal)
- 청산(주 로직): 3일 신저가 이탈 (채널청산, 저가 기준으로 장중 체크)
- 청산(안전판/하드스탑): 진입가 - min(1.5×ATR(10일), 진입가×7%) — 고정값, 트레일링 아님
- 추격매수 필터: 진입가(5일 신고가) 대비 0.5% 초과해서 오르면 스킵
- 휩쏘 필터: 직전 거래가 수익(win)이었으면 다음 신규 돌파는 스킵, 스킵 상태에서
  2xATR 더 유리하게 움직이면 오버라이드(강제 진입). 터틀과 동일 철학.
"""

import os
import pandas as pd
import requests

ENTRY_PERIOD = 5           # 5일 신고가 돌파 기준 (진입)
EXIT_PERIOD = 3            # 3일 신저가 이탈 기준 (채널청산)
WATCH_RATIO = 0.99         # 당일 고가 / 5일 최고가 >= 99% -> 관심
MAX_CHASE_RATIO = 0.005    # 진입가 대비 0.5% 초과 추격매수 스킵
ATR_PERIOD = 10            # 변동성 측정 기간 (짧은 호흡에 맞춰 10일로 단축)
ATR_MULTIPLIER = 1.5       # 하드스탑 ATR 배수
HARD_STOP_PCT = 0.07       # 하드스탑 퍼센트 캡 (진입가 대비 -7%)
TOP_PICKS_COUNT = 3        # 전체스캔 1회당 알림으로 뽑는 강력한 픽 개수


def calc_atr(df, period=ATR_PERIOD):
    high, low, close = df['High'], df['Low'], df['Close']
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def check_high5_breakout(df, entry_period=ENTRY_PERIOD, watch_ratio=WATCH_RATIO):
    """5일 신고가 돌파 판정 (진입용).

    n_high는 '전일 하루'가 아니라 오늘을 제외한 최근 entry_period(5)거래일 전체의
    최고가(rolling(entry_period).max().shift(1))로 계산한다. 즉 오늘 종가를
    "최근 5거래일 고점"과 비교하는 것이 기준이며, 이는 fresh_entry_signal 판정과
    아래 강도(strength) 점수 계산 모두에 동일하게 사용된다."""
    min_len = entry_period * 2 + ATR_PERIOD + 5
    if len(df) < min_len:
        return None
    df = df.copy()
    df['N_high'] = df['High'].rolling(entry_period).max().shift(1)
    df['ATR'] = calc_atr(df, ATR_PERIOD)
    df['entry_signal_series'] = df['Close'] > df['N_high']

    last = df.iloc[-1]
    if pd.isna(last['N_high']) or pd.isna(last['ATR']):
        return None

    entry_signal = bool(last['entry_signal_series'])
    ratio = last['High'] / last['N_high'] if last['N_high'] else None
    watch_signal = bool(ratio is not None and ratio >= watch_ratio and not entry_signal)

    lookback = df['entry_signal_series'].iloc[-(entry_period + 1):-1]
    was_recently_breaking = bool(lookback.any()) if len(lookback) > 0 else False
    fresh_entry_signal = bool(entry_signal and not was_recently_breaking)

    return {
        'entry_signal': entry_signal,
        'fresh_entry_signal': fresh_entry_signal,
        'watch_signal': watch_signal,
        'close': round(float(last['Close']), 4),
        'high': round(float(last['High']), 4),
        'n_high': round(float(last['N_high']), 4),
        'n_high_ratio': round(float(ratio), 4) if ratio is not None else None,
        'atr': round(float(last['ATR']), 4),
    }


def check_channel_exit(df, exit_period=EXIT_PERIOD):
    """보유 중인 포지션의 3일 신저가 채널청산 판정."""
    if len(df) < exit_period + 2:
        return None
    df = df.copy()
    df['N_low'] = df['Low'].rolling(exit_period).min().shift(1)
    last = df.iloc[-1]
    if pd.isna(last['N_low']):
        return None
    exit_signal = bool(last['Low'] <= last['N_low'])
    return {
        'exit_signal': exit_signal,
        'low': round(float(last['Low']), 4),
        'close': round(float(last['Close']), 4),
        'n_low': round(float(last['N_low']), 4),
    }


def calc_hard_stop(entry_price, atr_entry):
    """하이브리드 하드스탑: 1.5×ATR(10일)과 진입가 대비 -7% 중 더 타이트한(가까운) 쪽.
    실제 보유종목(수동 buy로 등록된 것) 관리에만 사용 — 자동스캔 파이프라인에는 쓰지 않음."""
    atr_dist = ATR_MULTIPLIER * atr_entry
    pct_dist = entry_price * HARD_STOP_PCT
    dist = min(atr_dist, pct_dist)
    return round(entry_price - dist, 4)


def check_high5_system(df):
    """자동스캔/재확인 파이프라인 전용: 5일신고가(진입)와 3일신저가(청산) 판정을
    한 번에 묶어서 반환한다 (터틀의 check_turtle_breakout이 entry_signal/exit_signal을
    한 번에 반환하는 것과 동일한 인터페이스로 맞춤). 실제 보유종목 관리는 이 함수를
    쓰지 않고 check_high5_breakout/check_channel_exit을 개별로 쓴다."""
    entry_res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
    if not entry_res:
        return None
    exit_res = check_channel_exit(df, EXIT_PERIOD)
    merged = dict(entry_res)
    merged['exit_signal'] = bool(exit_res and exit_res['exit_signal'])
    merged['n_low'] = exit_res['n_low'] if exit_res else None
    merged['low'] = exit_res['low'] if exit_res else None
    return merged


def pick_top_entries(df, top_n=TOP_PICKS_COUNT):
    """진입 신호 종목 중 '돌파 강도'가 큰 순서로 top_n개를 골라서 반환한다.

    강도(strength) = (오늘 종가 - 5일 최고가) / ATR(10일)
    → 5일 최고가(n_high, 오늘을 제외한 최근 5거래일 전체 기준)를 변동성(ATR) 대비
      얼마나 강하게 뚫고 올라왔는지를 나타내는 지표. 값이 클수록 더 강력한 돌파로 본다.
      (기존 '가장 신선한 돌파 1개'만 뽑던 pick_top_entry를 대체 — 신선도가 아니라
      강도 기준으로 3개를 뽑도록 완전히 교체됨)

    excess_ratio(초과율, (close-n_high)/n_high)는 참고용 정보로 함께 남겨둔다.
    후보가 top_n보다 적으면 있는 만큼만, 아예 없으면 빈 DataFrame을 반환한다."""
    entry_df = df[df['signal'] == '진입'].copy()
    if entry_df.empty:
        return entry_df
    entry_df['strength'] = (entry_df['close'] - entry_df['n_high']) / entry_df['atr']
    entry_df['excess_ratio'] = (entry_df['close'] - entry_df['n_high']) / entry_df['n_high']
    entry_df = entry_df.sort_values('strength', ascending=False)
    return entry_df.head(top_n)


# ===== 시장 판별 / 시세 조회 (텔레그램 명령어 처리용 공용 함수) =====

def detect_market(code_raw):
    """코드 문자열만 보고 시장을 자동 판별.
    KR: 6자리 숫자 / COIN: 빗썸 KRW 마켓에 실제 존재하는 티커 / 나머지: US"""
    code = code_raw.strip().upper()
    if code.isdigit() and len(code) == 6:
        return 'KR', code
    try:
        url = f"https://api.bithumb.com/public/ticker/{code}_KRW"
        res = requests.get(url, timeout=5).json()
        if res.get('status') == '0000':
            return 'COIN', code
    except Exception:
        pass
    return 'US', code


def fetch_ohlc(market, code, days=40):
    """시장별 최근 OHLC 히스토리 조회 (buy/추적확인 등 명령어 처리용 공용 함수)."""
    import FinanceDataReader as fdr
    import yfinance as yf
    from datetime import datetime, timedelta
    try:
        if market == 'KR':
            end = datetime.today()
            start = end - timedelta(days=days + 20)
            df = fdr.DataReader(str(code).zfill(6), start, end)
            return df if not df.empty else None
        elif market == 'US':
            data = yf.download(code, period=f'{days + 20}d', auto_adjust=True, progress=False)
            return data if not data.empty else None
        elif market == 'COIN':
            url = f"https://api.bithumb.com/public/candlestick/{code}_KRW/24h"
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
    except Exception:
        return None
    return None


def fetch_current_price(market, code):
    df = fetch_ohlc(market, code, days=5)
    if df is None or df.empty:
        return None
    return float(df.iloc[-1]['Close'])


def notify_telegram(message: str):
    token = os.environ.get('HIGH5_TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('HIGH5_TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={'chat_id': chat_id, 'text': message}, timeout=10)
    except Exception as e:
        print(f"텔레그램 알림 실패: {e}")


def send_long_message(text, chunk_size=3500):
    if not text:
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        candidate = f"{chunk}\n{line}" if chunk else line
        if len(candidate) > chunk_size:
            if chunk:
                notify_telegram(chunk)
            chunk = line
        else:
            chunk = candidate
    if chunk:
        notify_telegram(chunk)


def build_watch_summary(df, market_label):
    """관심종목(99~100% 구간) 전체를 정리해서 텔레그램 메시지로 반환. (신규 진입/전환 알림용)"""
    if df.empty:
        return None
    near_df = df[(df['n_high_ratio'] >= WATCH_RATIO) & (df['n_high_ratio'] <= 1.0)]
    if near_df.empty:
        return None
    near_df = near_df.sort_values('n_high_ratio', ascending=False)
    lines = [f"[{market_label}] 돌파임박 관심종목 {len(near_df)}개 (99~100% 구간)"]
    for _, r in near_df.iterrows():
        lines.append(
            f"- {r['name']}({r['code']})\n"
            f"  현재가 {r['close']} / 진입가(5일 신고가) {r['n_high']} "
            f"({r['n_high_ratio']*100:.1f}%)"
        )
    return "\n".join(lines)


def fmt_num(v):
    """NaN/None 방어 + 정수면 콤마, 소수면 4자리까지 정리."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "N/A"
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    if v == int(v):
        return f"{int(v):,}"
    return f"{v:,.4f}".rstrip('0').rstrip('.')


def fmt_pct(v):
    """NaN/None 방어 퍼센트 포맷 (부호 포함)."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "N/A"
        v = float(v)
    except (TypeError, ValueError):
        return "N/A"
    return f"{v:+.2f}%"


def trend_arrow(current, previous):
    """직전 값 대비 상승/하락/보합 표시 (터틀 스크리너와 동일 스타일).
    비교 대상 값(previous)이 없거나(최초) 숫자로 변환 안 되면 🆕 반환."""
    if previous is None or previous == '' or (isinstance(previous, float) and pd.isna(previous)):
        return "🆕"
    try:
        previous = float(previous)
        current = float(current)
    except (TypeError, ValueError):
        return "🆕"
    diff = current - previous
    if diff > 0:
        return f"🔴▲+{fmt_num(diff)}"
    elif diff < 0:
        return f"🔵▼{fmt_num(diff)}"
    return "🟡➖보합"


# ===== 휩쏘 필터 (터틀 스크리너와 동일 철학, market+code 기준으로 확장) =====
TRADE_HISTORY_COLUMNS = ['market', 'code', 'last_result', 'skip_active', 'skip_price']


def load_trade_history(path):
    if os.path.exists(path):
        df = pd.read_csv(path, dtype={'code': str, 'market': str})
        for col in TRADE_HISTORY_COLUMNS:
            if col not in df.columns:
                df[col] = ''
        return df[TRADE_HISTORY_COLUMNS]
    return pd.DataFrame(columns=TRADE_HISTORY_COLUMNS)


def save_trade_history(df, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def _get_history_row(hist_df, market, code):
    mask = (hist_df['market'] == market) & (hist_df['code'] == code)
    if mask.any():
        return hist_df[mask].iloc[0], mask
    return None, mask


def check_whipsaw(hist_df, market, code, breakout_price, current_price, atr):
    """직전 거래가 수익(win)이었으면 이번 신규 돌파는 스킵.
    스킵 상태에서 2xATR 더 유리하게 움직이면 오버라이드(강제 진입)."""
    row, mask = _get_history_row(hist_df, market, code)
    if row is None or row['last_result'] != 'win':
        return True, hist_df

    skip_active = str(row.get('skip_active')) == 'True'
    if not skip_active:
        hist_df.loc[mask, 'skip_active'] = True
        hist_df.loc[mask, 'skip_price'] = breakout_price
        return False, hist_df

    skip_price = float(row['skip_price'])
    override = current_price >= skip_price + 2 * atr
    if override:
        hist_df.loc[mask, 'skip_active'] = False
        hist_df.loc[mask, 'skip_price'] = ''
        return True, hist_df
    return False, hist_df


def record_trade_result(hist_df, market, code, entry_price, exit_price):
    """포지션이 청산될 때 승/패를 이력에 기록. 스킵 상태는 초기화."""
    row, mask = _get_history_row(hist_df, market, code)
    win = exit_price > entry_price
    result = 'win' if win else 'loss'
    if mask.any():
        hist_df.loc[mask, 'last_result'] = result
        hist_df.loc[mask, 'skip_active'] = False
        hist_df.loc[mask, 'skip_price'] = ''
    else:
        new_row = {'market': market, 'code': code, 'last_result': result,
                   'skip_active': False, 'skip_price': ''}
        hist_df = pd.concat([hist_df, pd.DataFrame([new_row])], ignore_index=True)
    return hist_df
