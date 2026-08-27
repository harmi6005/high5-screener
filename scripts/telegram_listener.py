# -*- coding: utf-8 -*-
"""텔레그램 명령어 폴링 리스너 (GitHub Actions에서 5분마다 자동 실행)

터틀 스크리너의 telegram_listener.py를 응용. 웹훅(Cloudflare Worker) 없이
getUpdates 폴링만으로 구현 — 터틀에서 웹훅 인프라(PAT 노출 등 보안이슈) 없이도
5분 내 응답이면 충분하다고 판단해서 채택.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import requests
from common import send_long_message, notify_telegram, load_trade_history, save_trade_history
from storage import load_positions, save_positions, load_tracked, save_tracked
from bot_commands import dispatch_lines

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
OFFSET_PATH = os.path.join(DATA_DIR, 'telegram_offset.txt')
HIST_PATH = os.path.join(DATA_DIR, 'trade_history.csv')


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
            return []
        print(f"getUpdates 실패: {desc}")
        return []
    return res.get('result', [])


if __name__ == "__main__":
    token = os.environ.get('HIGH5_TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('HIGH5_TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print("텔레그램 시크릿이 설정되어 있지 않아 종료합니다.")
        sys.exit(0)

    offset = get_offset()
    updates = get_updates(token, offset)
    if not updates:
        print("새 명령어 메시지가 없습니다.")
        sys.exit(0)

    pos_df = load_positions()
    tracked_df = load_tracked()
    hist_df = load_trade_history(HIST_PATH)

    pos_changed = False
    tracked_changed = False
    hist_changed = False
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
        pos_df, tracked_df, hist_df, reply, pc, tc, hc = dispatch_lines(text, pos_df, tracked_df, hist_df)
        pos_changed = pos_changed or pc
        tracked_changed = tracked_changed or tc
        hist_changed = hist_changed or hc
        if reply:
            send_long_message(reply)

    save_offset(max_update_id)
    if pos_changed:
        save_positions(pos_df)
    if tracked_changed:
        save_tracked(tracked_df)
    if hist_changed:
        save_trade_history(hist_df, HIST_PATH)

    print(f"처리 완료: 포지션변경={pos_changed}, 추적목록변경={tracked_changed}, 이력변경={hist_changed}")
