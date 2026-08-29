# -*- coding: utf-8 -*-
"""텔레그램 명령어 처리 공통 로직.

터틀 스크리너의 bot_commands.py 구조를 그대로 이식하고, 판정 기준만
5일신고가(진입) / 3일신저가+하이브리드 하드스탑(청산)으로 교체함.
telegram_listener.py(폴링, 5분마다)와 webhook_handler.py(웹훅, 즉시)가
둘 다 이 모듈의 함수를 가져다 쓴다.

지원 명령어:
- buy 코드 매수가
- sell 거래번호 [매도가]
- list
- 코드 추적시작
- 코드 추적종료 (추적해제/추적중지도 동일)
- 추적확인 (추적목록도 동일)
- 포지션확인 (포지션목록/보유확인도 동일)   ← 보유종목(positions.csv) 실시간 재조회
- 관심확인 (관심목록도 동일)               ← 관심종목(scan.csv) 실시간 재조회
- 명령어확인 (명령어 확인/도움말/help/(/help)도 동일)

포지션확인/관심확인은 5분 자동요약과 달리 장중/장마감 시간대와 무관하게
호출 즉시 현재가를 재조회해서 보여준다 (읽기 전용, CSV에 아무것도 안 씀).
"""

from datetime import datetime
import pandas as pd

from common import (ATR_PERIOD, ENTRY_PERIOD, WATCH_RATIO, EXIT_PERIOD,
                     calc_atr, calc_hard_stop, check_high5_breakout, check_channel_exit,
                     detect_market, fetch_ohlc, fetch_current_price, fmt_num)
from storage import gen_position_id, already_holding

START_WORDS = ('추적시작',)
STOP_WORDS = ('추적종료', '추적해제', '추적중지')
TRACK_CHECK_WORDS = ('추적확인', '추적목록')
POSITION_CHECK_WORDS = ('포지션확인', '포지션목록', '보유확인')
WATCH_CHECK_WORDS = ('관심확인', '관심목록')
HELP_WORDS = ('명령어확인', '명령어 확인', '도움말', 'help')


def get_atr(market, code, period=ATR_PERIOD):
    df = fetch_ohlc(market, code, days=period + 30)
    if df is None or len(df) < period + 1:
        return None
    atr_series = calc_atr(df, period)
    val = atr_series.iloc[-1]
    if pd.isna(val):
        return None
    return float(val)


# ===== 보유 포지션(positions) =====

def handle_buy(args, pos_df):
    if len(args) < 2:
        return pos_df, "형식: buy 코드 매수가\n예) buy BTC 5000000"

    code_raw = args[0].upper()
    try:
        buy_price = float(args[1])
    except ValueError:
        return pos_df, "매수가는 숫자로 입력해주세요."

    market, code = detect_market(code_raw)
    if already_holding(pos_df, market, code):
        return pos_df, f"{code}({market})는 이미 보유 중인 포지션이 있어요."

    atr = get_atr(market, code)
    if atr is None:
        return pos_df, (f"{code}의 변동성(ATR) 데이터를 가져오지 못해서 등록에 실패했어요.\n"
                         f"종목 코드가 맞는지 확인해주세요 (시장 판별: {market}).")

    hard_stop = calc_hard_stop(buy_price, atr)
    pid = gen_position_id(pos_df)
    new_row = {
        'position_id': pid, 'market': market, 'code': code, 'name': code,
        'entry_price': buy_price, 'atr_entry': round(atr, 6),
        'hard_stop_price': hard_stop, 'highest_price': buy_price,
        'last_milestone': 0, 'last_price': buy_price, 'last_n_low': '',
        'status': 'active', 'entry_date': datetime.today().strftime('%Y-%m-%d'),
    }
    pos_df = pd.concat([pos_df, pd.DataFrame([new_row])], ignore_index=True)

    return pos_df, (f"등록 완료 (거래번호 {pid})\n"
                     f"{code} [{market}]\n"
                     f"매수가 {fmt_num(buy_price)}\n"
                     f"하드스탑(1.5xATR10 / -7% 중 타이트한 쪽) {fmt_num(hard_stop)} (ATR≈{fmt_num(atr)})\n"
                     f"3일 신저가 또는 하드스탑 이탈 시 자동으로 팔리지 않아요. "
                     f"'매도 검토' 알림만 가고, sell {pid} 명령을 직접 입력해야 종료됩니다.\n"
                     f"5분마다 현재가/손익/청산가 추세를 담은 현황 알림이 계속 오고, "
                     f"포지션확인 명령으로 그 즉시 실시간 조회도 가능해요.")


def handle_sell(args, pos_df):
    if not args:
        return pos_df, "형식: sell 거래번호 [매도가]\n예) sell 4821 6200000"

    pid = args[0]
    sell_price = args[1] if len(args) > 1 else None

    # closed_manual만 아니면 종료 가능 (stop_hit 상태도 sell로 찾을 수 있어야 함)
    mask = (pos_df['position_id'] == pid) & (pos_df['status'] != 'closed_manual')
    if not mask.any():
        return pos_df, f"거래번호 {pid}를 찾지 못했어요. list 로 확인해보세요."

    row = pos_df[mask].iloc[0]
    extra = ""
    if sell_price:
        try:
            sp = float(sell_price)
            pnl = (sp - float(row['entry_price'])) / float(row['entry_price']) * 100
            extra = f"\n매도가 {fmt_num(sp)} / 손익률 {pnl:+.2f}%"
            pos_df.loc[mask, 'last_price'] = sp
        except ValueError:
            extra = "\n(매도가 형식이 숫자가 아니라 손익률 계산은 생략했어요)"

    pos_df.loc[mask, 'status'] = 'closed_manual'
    return pos_df, f"청산 완료 (거래번호 {pid}): {row['name']}({row['code']}) [{row['market']}]{extra}"


def handle_list(pos_df):
    active = pos_df[pos_df['status'] != 'closed_manual']
    if active.empty:
        return "현재 감시 중인 거래가 없어요."
    lines = ["현재 감시 중인 거래:"]
    for _, r in active.iterrows():
        tag = " [손절확정/매도대기]" if r['status'] == 'stop_hit' else ""
        lines.append(f"[{r['position_id']}] {r['name']}({r['code']}) [{r['market']}]{tag} "
                      f"매수 {fmt_num(r['entry_price'])} / 최고가 {fmt_num(r['highest_price'])} / "
                      f"하드스탑 {fmt_num(r['hard_stop_price'])} / {r['last_milestone']}배 수익 도달")
    return "\n".join(lines)


def handle_position_check(pos_df):
    """`list`와 달리, 호출한 그 순간 현재가를 실시간 재조회해서 보여준다
    (장중/장마감 시간대와 무관하게 항상 동작, 읽기 전용 — CSV에 아무것도 안 씀)."""
    active = pos_df[pos_df['status'] != 'closed_manual']
    if active.empty:
        return "현재 감시 중인 보유종목이 없어요."

    lines = [f"포지션 실시간 확인 {len(active)}건:"]
    for _, row in active.iterrows():
        market, code = row['market'], row['code']
        price = fetch_current_price(market, code)
        if price is None:
            lines.append(f"- [{row['position_id']}] {row['name']}({code}) [{market}]: 현재가 조회 실패")
            continue

        try:
            entry_price = float(row['entry_price'])
            hard_stop_price = float(row['hard_stop_price'])
        except (TypeError, ValueError):
            lines.append(f"- [{row['position_id']}] {row['name']}({code}) [{market}]: 데이터 이상, 건너뜀")
            continue

        pnl_pct = (price - entry_price) / entry_price * 100 if entry_price else None
        gap_pct = (price - hard_stop_price) / hard_stop_price * 100 if hard_stop_price else None

        if row['status'] == 'stop_hit':
            tag = "🔴 손절확정 (매도대기)"
        elif gap_pct is not None and gap_pct <= 3.0:
            tag = "🔶 하드스탑 근접"
        else:
            tag = "🟢 정상"

        n_low_str = "N/A"
        hist = fetch_ohlc(market, code, days=20)
        if hist is not None:
            channel = check_channel_exit(hist, EXIT_PERIOD)
            if channel:
                n_low_str = fmt_num(channel['n_low'])

        pnl_str = f"{pnl_pct:+.2f}%" if pnl_pct is not None else "N/A"
        gap_str = f" (남은거리 {gap_pct:+.2f}%)" if gap_pct is not None else ""

        lines.append(
            f"- [{row['position_id']}] {row['name']}({code}) [{market}] {tag}\n"
            f"  현재가 {fmt_num(price)} / 매수가 {fmt_num(entry_price)} (손익 {pnl_str})\n"
            f"  3일저가선 {n_low_str} / 하드스탑 {fmt_num(hard_stop_price)}{gap_str}"
        )
    return "\n".join(lines)


# ===== 자동스캔 관심종목(scan.csv) 실시간 확인 =====

def handle_watch_check(scan_df):
    """scan.csv의 signal=='관심' 종목들을 호출 즉시 현재가로 재조회해서 보여준다
    (5분 자동요약과 별개, 시간대 무관, 읽기 전용 — CSV에 아무것도 안 씀)."""
    if scan_df is None or scan_df.empty:
        return "현재 관심종목이 없어요."

    watch_df = scan_df[scan_df['signal'] == '관심']
    if watch_df.empty:
        return "현재 관심종목이 없어요."

    lines = [f"관심종목 실시간 확인 {len(watch_df)}종목:"]
    for _, row in watch_df.iterrows():
        market, code = row['market'], row['code']
        price = fetch_current_price(market, code)
        if price is None:
            lines.append(f"- {row['name']}({code}) [{market}]: 현재가 조회 실패")
            continue

        try:
            n_high = float(row['n_high'])
        except (TypeError, ValueError):
            n_high = None

        ratio = price / n_high if n_high else None
        ratio_str = f"{ratio*100:.1f}%" if ratio is not None else "N/A"
        if ratio is not None and ratio >= 1.0:
            tag = "⚡ 돌파(재확인 대기)"
        elif ratio is not None and ratio >= 0.99:
            tag = "🔶 돌파임박"
        else:
            tag = "🟢 관찰중"

        n_high_str = fmt_num(n_high) if n_high is not None else "N/A"
        lines.append(
            f"- {row['name']}({code}) [{market}] {tag}\n"
            f"  현재가 {fmt_num(price)} / 5일고가선 {n_high_str} ({ratio_str})"
        )
    return "\n".join(lines)


# ===== 감시목록(tracked / 추적) =====

def handle_track_start(code_raw, tracked_df):
    market, code = detect_market(code_raw)
    if ((tracked_df['code'] == code) & (tracked_df['market'] == market)).any():
        return tracked_df, f"{code}는 이미 추적 중이에요."
    new_row = {'code': code, 'market': market, 'status': ''}
    tracked_df = pd.concat([tracked_df, pd.DataFrame([new_row])], ignore_index=True)
    return tracked_df, f"추적시작: {code} [{market}]\n관심/진입/청산 신호가 바뀔 때마다 알림 드릴게요."


def handle_track_stop(code_raw, tracked_df):
    market, code = detect_market(code_raw)
    before = len(tracked_df)
    tracked_df = tracked_df[~((tracked_df['code'] == code) & (tracked_df['market'] == market))]
    if len(tracked_df) == before:
        return tracked_df, f"{code}는 추적 중이 아니에요."
    return tracked_df, f"추적종료: {code}"


def handle_track_check(tracked_df):
    """지금 이 순간 실시간으로 재조회해서 현재 상태를 분석해 보여준다."""
    if tracked_df.empty:
        return "현재 추적 중인 종목이 없어요."

    min_len = ENTRY_PERIOD * 2 + ATR_PERIOD + 5
    lines = [f"추적 중인 종목 {len(tracked_df)}개 실시간 분석:"]
    for _, row in tracked_df.iterrows():
        code, market = row['code'], row['market']
        df = fetch_ohlc(market, code, days=60)
        if df is None or len(df) < min_len:
            lines.append(f"- {code} [{market}]: 데이터 조회 실패")
            continue

        res = check_high5_breakout(df, ENTRY_PERIOD, WATCH_RATIO)
        if not res:
            lines.append(f"- {code} [{market}]: 데이터 부족")
            continue
        channel = check_channel_exit(df, EXIT_PERIOD)

        if res['entry_signal']:
            status = '진입'
        elif channel and channel['exit_signal']:
            status = '청산'
        elif res['watch_signal']:
            status = '관심'
        else:
            status = '관찰중'

        gap_pct = (res['close'] - res['n_high']) / res['n_high'] * 100
        n_low_str = fmt_num(channel['n_low']) if channel else "N/A"
        lines.append(
            f"- {code} [{market}]: {status} | 현재가 {res['close']} / "
            f"5일고가 {res['n_high']} ({gap_pct:+.2f}%) / 3일저가 {n_low_str}"
        )
    return "\n".join(lines)


def handle_help():
    return (
        "buy 코드 매수가\n"
        "  예) buy 005930 71000\n\n"
        "sell 거래번호 [매도가]\n"
        "  예) sell 4821 또는 sell 4821 73000\n\n"
        "list\n"
        "  현재 감시 중인 거래 목록 (등록된 값 기준)\n\n"
        "포지션확인 (포지션목록/보유확인도 동일)\n"
        "  보유종목을 지금 이 순간 실시간 재조회\n\n"
        "코드 추적시작 (예: 005930 추적시작)\n"
        "코드 추적종료 (추적해제/추적중지도 동일)\n"
        "추적확인 (추적목록도 동일)\n"
        "  추적목록을 지금 이 순간 실시간 재조회\n\n"
        "관심확인 (관심목록도 동일)\n"
        "  자동스캔 관심종목을 지금 이 순간 실시간 재조회\n\n"
        "명령어확인 (도움말/help도 동일)"
    )


def dispatch(text, pos_df, tracked_df, scan_df):
    """명령어 텍스트 1개를 해석해서 처리한다.
    반환값: (pos_df, tracked_df, reply_text_or_None, is_long_reply, pos_changed, tracked_changed)
    scan_df는 관심확인 조회 전용(읽기만 함, 변경/저장 없음)."""
    text = text.strip()
    if not text:
        return pos_df, tracked_df, None, False, False, False

    parts = text.split()
    cmd = parts[0].lower().lstrip('/')
    args = parts[1:]

    reply = None
    is_long = False
    pos_changed = False
    tracked_changed = False

    if cmd == 'buy':
        pos_df, reply = handle_buy(args, pos_df)
        pos_changed = True
    elif cmd == 'sell':
        pos_df, reply = handle_sell(args, pos_df)
        pos_changed = True
    elif cmd == 'list':
        reply = handle_list(pos_df)
    elif text in POSITION_CHECK_WORDS:
        reply = handle_position_check(pos_df)
        is_long = True
    elif text in WATCH_CHECK_WORDS:
        reply = handle_watch_check(scan_df)
        is_long = True
    elif len(parts) == 2 and parts[1] in START_WORDS:
        tracked_df, reply = handle_track_start(parts[0], tracked_df)
        tracked_changed = True
    elif len(parts) == 2 and parts[1] in STOP_WORDS:
        tracked_df, reply = handle_track_stop(parts[0], tracked_df)
        tracked_changed = True
    elif text in TRACK_CHECK_WORDS:
        reply = handle_track_check(tracked_df)
        is_long = True
    elif text in HELP_WORDS or cmd == 'help':
        reply = handle_help()

    return pos_df, tracked_df, reply, is_long, pos_changed, tracked_changed


def dispatch_lines(text, pos_df, tracked_df, scan_df):
    """여러 줄로 온 명령어를 줄 단위로 각각 처리하고 답장을 합쳐서 반환.
    반환값: (pos_df, tracked_df, combined_reply, pos_changed, tracked_changed)"""
    replies = []
    pos_changed_any = False
    tracked_changed_any = False

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        pos_df, tracked_df, reply, _is_long, pos_changed, tracked_changed = dispatch(
            line, pos_df, tracked_df, scan_df)
        if reply:
            replies.append(reply)
        pos_changed_any = pos_changed_any or pos_changed
        tracked_changed_any = tracked_changed_any or tracked_changed

    combined_reply = "\n\n".join(replies) if replies else None
    return pos_df, tracked_df, combined_reply, pos_changed_any, tracked_changed_any
