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
    """5일 신고가 돌파 판정 (진입용)."""
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
    """하이브리드 하드스탑: 1.5×ATR(10일)과 진입가 대비 -7% 중 더 타이트한(가까운) 쪽."""
    atr_dist = ATR_MULTIPLIER * atr_entry
    pct_dist = entry_price * HARD_STOP_PCT
    dist = min(atr_dist, pct_dist)
    return round(entry_price - dist, 4)


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
    비교 대상 값(previous)이 없거나(최초) 숫자로 변환 안 되면 🆕 반환.
    가격 뿐 아니라 임의의 두 숫자(예: 채널청산선) 비교에도 재사용 가능."""
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
