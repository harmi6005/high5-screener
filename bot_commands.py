# -*- coding: utf-8 -*-
"""텔레그램 명령어 처리 공통 로직 (터틀 스크리너의 bot_commands.py를 high5 구조에 맞게 응용)

지원 명령어:
- buy 코드 매수가          : 수동 포지션 등록 (하드스탑 자동계산, 자동 진입파이프라인과 별개)
- sell 거래번호 [매도가]   : 포지션 청산 (매도가 생략 시 현재가 자동조회)
- list                     : 보유 포지션 목록
- 코드 추적시작            : 감시목록(tracked.csv) 등록
- 코드 추적종료/추적해제/추적중지 : 감시목록 해제
- 추적확인/추적목록        : 감시목록 실시간 재조회
- 명령어확인/명령어 확인/도움말/help/(/help) : 사용법 안내

dispatch(text, pos_df, tracked_df, hist_df)는 한 줄짜리 명령어 하나를 처리하고
(pos_df, tracked_df, hist_df, reply, is_long, pos_changed, tracked_changed, hist_changed)를 반환한다.
dispatch_lines는 여러 줄 명령어를 한 메시지로 받았을 때 줄 단위로 각각 처리한다
(터틀에서 겪었던 "여러 줄 중 첫 줄만 처리되는" 버그를 처음부터 방지).
"""

from datetime import datetime
import pandas as pd

from common import (ATR_PERIOD, ENTRY_PERIOD, WATCH_RATIO, EXIT_PERIOD,
                     calc_atr, calc_hard_stop, check_high5_breakout, check_channel_exit,
                     detect_market, fetch_ohlc, fetch_current_price,
                     fmt_num, fmt_pct, record_trade_result)
from storage import gen_position_id, already_holding

TRACK_START_KEYWORDS = {'추적시작'}
TRACK_STOP_KEYWORDS = {'추적종료', '추적해제', '추적중지'}
TRACK_CHECK_KEYWORDS = {'추적확인', '추적목록'}
LIST_KEYWORDS = {'list', '목록'}
HELP_KEYWORDS = {'명령어확인', '명령어 확인', '도움말', 'help', '/help'}


def handle_help():
    return (
        "📖 5일신고가·3일신저가 봇 명령어\n\n"
        "buy 코드 매수가\n"
        "  - 수동 포지션 등록 (하드스탑 자동계산). 예: buy 005930 71000\n\n"
        "sell 거래번호 [매도가]\n"
        "  - 포지션 청산, 매도가 생략 시 현재가 자동조회. 예: sell 0042 또는 sell 0042 73000\n\n"
        "list\n"
        "  - 현재 보유 중인 포지션 목록\n\n"
        "코드 추적시작 (예: 005930 추적시작)\n"
        "  - 자동매매와 별개로 특정 종목을 수동 감시목록에 등록\n\n"
        "코드 추적종료 (추적해제/추적중지도 동일)\n"
        "  - 감시목록에서 해제\n\n"
        "추적확인 (추적목록도 동일)\n"
        "  - 감시목록 종목들을 그 순간 실시간 재조회해서 상태 보여줌\n\n"
        "명령어확인 (도움말/help도 동일)\n"
        "  - 이 안내"
    )


def handle_buy(args, pos_df):
    if len(args) < 2:
        return pos_df, "사용법: buy 코드 매수가 (예: buy 005930 71000)", False

    code_raw, price_str = args[0], args[1]
    try:
        price = float(price_str)
    except ValueError:
        return pos_df, "매수가는 숫자로 입력해주세요.", False

    market, code = detect_market(code_raw)
    if already_holding(pos_df, market, code):
        return pos_df, f"{code}({market})는 이미 보유 중인 포지션이 있습니다.", False

    hist = fetch_ohlc(market, code, days=40)
    min_len = ATR_PERIOD + 5
    if hist is None or len(hist) < min_len:
        return pos_df, f"{code}({market}) 데이터 조회 실패 또는 데이터 부족.", False

    atr_series = calc_atr(hist, ATR_PERIOD)
    atr = float(atr_series.iloc[-1])
    if pd.isna(atr):
        return pos_df, f"{code}({market}) ATR 계산 실패 (데이터 부족).", False

    hard_stop = calc_hard_stop(price, atr)
    pid = gen_position_id(pos_df)
    new_pos = {
        'position_id': pid, 'market': market, 'code': code, 'name': code,
        'entry_price': price, 'atr_entry': round(atr, 4),
        'hard_stop_price': hard_stop, 'highest_price': price,
        'last_milestone': 0, 'last_price': price, 'last_n_low': '',
        'status': 'active', 'entry_date': datetime.today().strftime('%Y-%m-%d'),
    }
    pos_df = pd.concat([pos_df, pd.DataFrame([new_pos])], ignore_index=True)
    reply = (
        f"✅ 수동 매수 등록 완료 [거래번호 {pid}]\n"
        f"{code} ({market}) / 매수가 {fmt_num(price)}\n"
        f"하드스탑 {fmt_num(hard_stop)} (ATR10 {fmt_num(atr)} 기준)"
    )
    return pos_df, reply, True


def handle_sell(args, pos_df, hist_df):
    if not args:
        return pos_df, hist_df, "사용법: sell 거래번호 [매도가] (예: sell 0042 또는 sell 0042 73000)", False, False

    pid = args[0]
    mask = (pos_df['position_id'] == pid) & (pos_df['status'] == 'active')
    if not mask.any():
        return pos_df, hist_df, f"거래번호 {pid}를 찾을 수 없거나 이미 종료된 거래입니다.", False, False

    row = pos_df[mask].iloc[0]
    if len(args) >= 2:
        try:
            sell_price = float(args[1])
        except ValueError:
            return pos_df, hist_df, "매도가는 숫자로 입력해주세요.", False, False
    else:
        sell_price = fetch_current_price(row['market'], row['code'])
        if sell_price is None:
            return (pos_df, hist_df,
                    f"{row['code']}({row['market']}) 현재가 조회 실패. 매도가를 직접 입력해주세요.",
                    False, False)

    entry_price = float(row['entry_price'])
    pnl_pct = (sell_price - entry_price) / entry_price * 100 if entry_price else None

    pos_df.loc[mask, 'status'] = 'closed_manual'
    pos_df.loc[mask, 'last_price'] = sell_price
    hist_df = record_trade_result(hist_df, row['market'], row['code'], entry_price, sell_price)

    reply = (
        f"✅ 수동 매도 처리 완료 [거래번호 {pid}]\n"
        f"{row['name']}({row['code']}) / 매수가 {fmt_num(entry_price)} → 매도가 {fmt_num(sell_price)}\n"
        f"손익률 {fmt_pct(pnl_pct)}"
    )
    return pos_df, hist_df, reply, True, True


def handle_list(pos_df):
    active = pos_df[pos_df['status'] == 'active']
    if active.empty:
        return "현재 보유 중인 포지션이 없습니다."
    lines = [f"📋 보유 포지션 {len(active)}건"]
    for _, r in active.iterrows():
        entry_price = pd.to_numeric(r['entry_price'], errors='coerce')
        last_price = pd.to_numeric(r['last_price'], errors='coerce')
        pnl_pct = ((last_price - entry_price) / entry_price * 100
                   if pd.notna(entry_price) and entry_price and pd.notna(last_price) else None)
        lines.append(
            f"- [{r['position_id']}] {r['name']}({r['code']}) [{r['market']}]\n"
            f"  매수가 {fmt_num(entry_price)} / 현재가 {fmt_num(last_price)} (손익 {fmt_pct(pnl_pct)})\n"
            f"  하드스탑 {fmt_num(r['hard_stop_price'])} / 최고가 {fmt_num(r['highest_price'])}"
        )
    return "\n".join(lines)


def handle_track_start(args, tracked_df):
    if not args:
        return tracked_df, "사용법: 코드 추적시작 (예: 005930 추적시작)", False
    market, code = detect_market(args[0])
    if ((tracked_df['market'] == market) & (tracked_df['code'] == code)).any():
        return tracked_df, f"{code}({market})는 이미 추적 중입니다.", False
    new_row = {'market': market, 'code': code, 'name': code}
    tracked_df = pd.concat([tracked_df, pd.DataFrame([new_row])], ignore_index=True)
    return tracked_df, f"✅ {code}({market}) 추적 시작", True


def handle_track_stop(args, tracked_df):
    if not args:
        return tracked_df, "사용법: 코드 추적종료 (예: 005930 추적종료)", False
    market, code = detect_market(args[0])
    mask = (tracked_df['market'] == market) & (tracked_df['code'] == code)
    if not mask.any():
        return tracked_df, f"{code}({market})는 추적 목록에 없습니다.", False
    tracked_df = tracked_df[~mask].reset_index(drop=True)
    return tracked_df, f"✅ {code}({market}) 추적 종료", True


def handle_track_check(tracked_df):
    if tracked_df.empty:
        return "현재 추적 중인 종목이 없습니다."
    lines = [f"🔍 추적목록 실시간 확인 {len(tracked_df)}건"]
    min_len = ENTRY_PERIOD * 2 + ATR_PERIOD + 5
    for _, r in tracked_df.iterrows():
        hist = fetch_ohlc(r['market'], r['code'], days=40)
        if hist is None or len(hist) < min_len:
            lines.append(f"- {r['code']}({r['market']}): 데이터 조회 실패/부족")
            continue
        res = check_high5_breakout(hist, ENTRY_PERIOD, WATCH_RATIO)
        if not res:
            lines.append(f"- {r['code']}({r['market']}): 데이터 부족")
            continue
        channel = check_channel_exit(hist, EXIT_PERIOD)
        if res['entry_signal']:
            status = "🔴 진입가능(5일신고가 돌파)"
        elif res['watch_signal']:
            status = "🔶 관심(돌파임박)"
        else:
            status = "🟢 관찰중"
        n_low_str = fmt_num(channel['n_low']) if channel else "N/A"
        ratio_str = f"{res['n_high_ratio']*100:.1f}%" if res['n_high_ratio'] is not None else "N/A"
        lines.append(
            f"- {r['code']}({r['market']}) {status}\n"
            f"  현재가 {fmt_num(res['close'])} / 5일고가선 {fmt_num(res['n_high'])} ({ratio_str})\n"
            f"  3일저가선 {n_low_str}"
        )
    return "\n".join(lines)


def dispatch(text, pos_df, tracked_df, hist_df):
    """한 줄짜리 명령어 텍스트 하나를 처리.
    반환: (pos_df, tracked_df, hist_df, reply, is_long, pos_changed, tracked_changed, hist_changed)"""
    text = text.strip()
    if not text:
        return pos_df, tracked_df, hist_df, None, False, False, False, False

    lowered = text.lower()

    if lowered in HELP_KEYWORDS:
        return pos_df, tracked_df, hist_df, handle_help(), False, False, False, False

    if lowered in LIST_KEYWORDS:
        return pos_df, tracked_df, hist_df, handle_list(pos_df), True, False, False, False

    if text in TRACK_CHECK_KEYWORDS or lowered in TRACK_CHECK_KEYWORDS:
        return pos_df, tracked_df, hist_df, handle_track_check(tracked_df), True, False, False, False

    parts = text.split()

    if len(parts) >= 2 and parts[1] in TRACK_START_KEYWORDS:
        tracked_df, reply, changed = handle_track_start([parts[0]], tracked_df)
        return pos_df, tracked_df, hist_df, reply, False, False, changed, False

    if len(parts) >= 2 and parts[1] in TRACK_STOP_KEYWORDS:
        tracked_df, reply, changed = handle_track_stop([parts[0]], tracked_df)
        return pos_df, tracked_df, hist_df, reply, False, False, changed, False

    if parts and parts[0].lower() == 'buy':
        pos_df, reply, changed = handle_buy(parts[1:], pos_df)
        return pos_df, tracked_df, hist_df, reply, False, changed, False, False

    if parts and parts[0].lower() == 'sell':
        pos_df, hist_df, reply, pos_changed, hist_changed = handle_sell(parts[1:], pos_df, hist_df)
        return pos_df, tracked_df, hist_df, reply, False, pos_changed, False, hist_changed

    return pos_df, tracked_df, hist_df, None, False, False, False, False


def dispatch_lines(text, pos_df, tracked_df, hist_df):
    """여러 줄로 온 명령어를 줄 단위로 각각 처리하고 답장을 합쳐서 반환.
    반환: (pos_df, tracked_df, hist_df, combined_reply, pos_changed, tracked_changed, hist_changed)"""
    replies = []
    pos_changed_any = False
    tracked_changed_any = False
    hist_changed_any = False

    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        pos_df, tracked_df, hist_df, reply, _is_long, pos_changed, tracked_changed, hist_changed = dispatch(
            line, pos_df, tracked_df, hist_df)
        if reply:
            replies.append(reply)
        pos_changed_any = pos_changed_any or pos_changed
        tracked_changed_any = tracked_changed_any or tracked_changed
        hist_changed_any = hist_changed_any or hist_changed

    combined_reply = "\n\n".join(replies) if replies else None
    return pos_df, tracked_df, hist_df, combined_reply, pos_changed_any, tracked_changed_any, hist_changed_any
