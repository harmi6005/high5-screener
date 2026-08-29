# -*- coding: utf-8 -*-
"""텔레그램 웹훅으로 즉시 전달된 명령어 1건을 처리 (repository_dispatch로 트리거됨)

포지션확인/관심확인 명령을 지원하기 위해 scan.csv도 함께 로드해서 dispatch_lines에
넘긴다 (읽기 전용, 여기서 scan.csv를 저장하지는 않음)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from common import send_long_message
from storage import load_positions, save_positions, load_tracked, save_tracked, load_scan
from bot_commands import dispatch_lines

if __name__ == "__main__":
    text = os.environ.get('COMMAND_TEXT', '').strip()
    if not text:
        print("처리할 명령어 텍스트가 없습니다 (COMMAND_TEXT 비어있음).")
        sys.exit(0)

    print(f"웹훅으로 받은 명령어: {text}")

    pos_df = load_positions()
    tracked_df = load_tracked()
    scan_df = load_scan()

    pos_df, tracked_df, reply, pos_changed, tracked_changed = dispatch_lines(
        text, pos_df, tracked_df, scan_df)

    if reply:
        send_long_message(reply)
    else:
        print("인식된 명령어가 아니라서 응답하지 않았습니다.")

    if pos_changed:
        save_positions(pos_df)
    if tracked_changed:
        save_tracked(tracked_df)

    print("웹훅 처리 완료")
