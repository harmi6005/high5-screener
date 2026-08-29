# -*- coding: utf-8 -*-
"""텔레그램 명령어 폴링 리스너 (GitHub Actions에서 5분마다 자동 실행)

터틀 스크리너의 telegram_listener.py를 그대로 이식. 웹훅이 활성화되어 있으면
getUpdates가 에러를 반환하는데, 이 경우 조용히 건너뛰도록 방어함
(웹훅을 나중에 해제하면 폴링이 자동으로 다시 살아남).

포지션확인/관심확인 명령을 지원하기 위해 scan.csv도 함께 로드해서 dispatch_lines에
넘긴다 (읽기 전용, 여기서 scan.csv를 저장하지는 않음 — 그건 recheck/watchlist_check
스크립트의 몫).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from common import send_long_message
from storage import load_positions, save_positions, load_tracked, save_tracked, load_scan
from bot_commands import dispatch_lines

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OFFSET_PATH = os.path.join(DATA_DIR, 'telegram_offset.txt')


def get_offset():
    if os.path.exists(OFFSET_PATH):
        with open(OFFSET_PATH) as f:
            content = f.read().strip()
            return int(content) if content else 0
    return 0


def save_offset(offset):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OFFSET_PATH, 'w') as f:
        f.write(str(offset))


def get_updates(token, offset):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {'offset': offset, 'timeout': 5}
    res = requests.get(url, params=params, timeout=15).json()
    if not res.get('ok', True):
        desc = res.get('description', '')
        if 'webhook' in desc.lower():
            print(f"웹훅이 활성화되어 있어 폴링을 건너뜁니다: {desc}")
        else:
            print(f"getUpdates 실패: {desc}")
        return []
    return res.get('result', [])


if __name__ == "__main__":
    token = os.environ.get('HIGH5_TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('HIGH5_TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("텔레그램 설정이 없어서 명령어 처리를 건너뜁니다.")
        sys.exit(0)

    offset = get_offset()
    updates = get_updates(token, offset)
    if not updates:
        print("새 명령어 없음 (웹훅이 켜져 있으면 항상 이렇게 나오는 게 정상이에요)")
        sys.exit(0)

    pos_df = load_positions()
    tracked_df = load_tracked()
    scan_df = load_scan()

    pos_changed = False
    tracked_changed = False
    max_update_id = offset

    for update in updates:
        max_update_id = max(max_update_id, update['update_id'] + 1)
        message = update.get('message') or update.get('edited_message')
        if not message:
            continue
        msg_chat_id = str(message.get('chat', {}).get('id'))
        if msg_chat_id != str(chat_id):
            print(f"등록된 chat_id가 아닌 메시지 무시: {msg_chat_id}")
            continue
        text = message.get('text', '')
        if not text:
            continue

        print(f"명령어 처리: {text}")
        pos_df, tracked_df, reply, p_changed, t_changed = dispatch_lines(
            text, pos_df, tracked_df, scan_df)
        pos_changed = pos_changed or p_changed
        tracked_changed = tracked_changed or t_changed
        if reply:
            send_long_message(reply)

    save_offset(max_update_id)
    if pos_changed:
        save_positions(pos_df)
    if tracked_changed:
        save_tracked(tracked_df)

    print("명령어 처리 완료")
