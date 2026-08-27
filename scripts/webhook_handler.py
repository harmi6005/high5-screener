# -*- coding: utf-8 -*-
"""텔레그램 웹훅으로 즉시 전달된 명령어 1건을 처리 (repository_dispatch로 트리거됨)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import send_long_message
from storage import load_positions, save_positions, load_tracked, save_tracked
from bot_commands import dispatch_lines

if __name__ == "__main__":
    text = os.environ.get('COMMAND_TEXT', '').strip()
    if not text:
        print("처리할 명령어 텍스트가 없습니다 (COMMAND_TEXT 비어있음).")
        sys.exit(0)

    print(f"웹훅으로 받은 명령어: {text}")

    pos_df = load_positions()
    tracked_df = load_tracked()

    pos_df, tracked_df, reply, pos_changed, tracked_changed = dispatch_lines(text, pos_df, tracked_df)

    if reply:
        send_long_message(reply)
    else:
        print("인식된 명령어가 아니라서 응답하지 않았습니다.")

    if pos_changed:
        save_positions(pos_df)
    if tracked_changed:
        save_tracked(tracked_df)

    print("웹훅 처리 완료")
