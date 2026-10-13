"""Khởi động bộ xử lý cục bộ và mở trình duyệt. Chỉ lắng nghe 127.0.0.1."""
from __future__ import annotations
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn


def port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) != 0


def pick_port(host, wanted):
    for candidate in range(wanted, wanted + 10):
        if port_free(host, candidate):
            return candidate
    raise SystemExit(f'Các cổng {wanted}–{wanted+9} đều bận. Đóng chương trình cũ hoặc đặt MEETING_PORT khác.')


if __name__ == '__main__':
    host = '127.0.0.1'
    wanted = int(os.getenv('MEETING_PORT', '8765'))
    port = pick_port(host, wanted)
    if port != wanted:
        print(f'[MeetingScribe] Cổng {wanted} đang bận, dùng cổng {port}.')
    url = f'http://{host}:{port}'
    print(f'[MeetingScribe] Mở trình duyệt Chrome/Edge tại {url} — giữ cửa sổ này mở trong suốt cuộc họp.')
    if os.getenv('MEETING_NO_BROWSER') != '1':
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(url)), daemon=True).start()
    try:
        uvicorn.run('app:app', host=host, port=port, log_level='info', reload=False, ws_max_size=4 * 1024 * 1024)
    except KeyboardInterrupt:
        sys.exit(0)
