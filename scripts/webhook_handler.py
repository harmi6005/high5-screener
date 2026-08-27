# -*- coding: utf-8 -*-
"""텔레그램 웹훅으로 즉시 전달된 명령어 1건을 처리 (repository_dispatch로 트리거됨)

흐름: 텔레그램 메시지 → Cloudflare Worker(즉시 수신) → GitHub repository_dispatch API 호출
→ .github/workflows/telegram_webhook.yml 트리거 → 이 스크립트 실행 → 답장 발송
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import send_long_message, load_trade_history, save_trade_history
from storage import load_positions, save_positions, load_tracked, save_tracked
from bot_commands import dispatch_lines

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')

if __name__ == "__main__":
    text = os.environ.get('COMMAND_TEXT', '').strip()
    if not text:
        print("처리할 명령어 텍스트가 없습니다 (COMMAND_TEXT 비어있음).")
        sys.exit(0)

    print(f"웹훅으로 받은 명령어: {text}")

    pos_df = load_positions()
    tracked_df = load_tracked()
    hist_df = load_trade_history(HIST_PATH)

    pos_df, tracked_df, hist_df, reply, pos_changed, tracked_changed, hist_changed = dispatch_lines(
        text, pos_df, tracked_df, hist_df)

    if reply:
        send_long_message(reply)
    else:
        print("인식되지 않은 명령어라 답장을 보내지 않습니다.")

    if pos_changed:
        save_positions(pos_df)
    if tracked_changed:
        save_tracked(tracked_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    print(f"웹훅 처리 완료: 포지션변경={pos_changed}, 추적목록변경={tracked_changed}, 이력변경={hist_changed}")
