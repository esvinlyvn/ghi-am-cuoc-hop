import json
import struct
import time
import wave

from fastapi.testclient import TestClient

import app
from browser_capture import BrowserPCMWriter


class FakeSegment:
    start = 0
    end = .5
    text = 'Âm thanh cuộc họp từ một tab được chọn.'


class FakeWhisper:
    def transcribe(self, *args, **kwargs):
        return iter([FakeSegment()]), None


def pcm(seconds, value=1500, rate=16000):
    return struct.pack('<h', value) * int(seconds * rate)


def wait_for(c, mid, cond, tries=120, pause=0.025):
    m = None
    for _ in range(tries):
        m = c.get(f'/api/meetings/{mid}').json()
        if cond(m):
            return m
        time.sleep(pause)
    return m


def test_browser_pcm_writer_rotates_and_keeps_sample_accurate_timestamps(tmp_path):
    received = []
    w = BrowserPCMWriter(tmp_path, 'browser1', 16000, 100, lambda *a: received.append(a), lambda *a: None)
    for k in range(45):  # 45 giây liên tục, gửi hơi trễ so với thời gian thực
        w.push(pcm(1), at_time=110 + k + 0.3)
    w.close()
    assert len(received) == 3
    starts = [r[1] for r in received]
    # Đoạn đầu bắt đầu ~ (110.3-1) - 100 = 9.3 s; các đoạn sau cách đúng 20 s theo số mẫu.
    assert abs(starts[0] - 9.3) < 0.01
    assert abs(starts[1] - starts[0] - 20) < 1e-6 and abs(starts[2] - starts[1] - 20) < 1e-6
    assert [round(r[2]) for r in received] == [20, 20, 5]
    assert all(f.exists() for *_, f in received)
    with wave.open(str(received[0][-1])) as wav:
        assert wav.getframerate() == 16000 and wav.getnframes() == 320000


def test_browser_pcm_writer_gap_opens_new_chunk_on_wall_clock(tmp_path):
    received = []
    w = BrowserPCMWriter(tmp_path, 'browser2', 16000, 0, lambda *a: received.append(a), lambda *a: None)
    w.push(pcm(2), at_time=5)
    w.push(pcm(2), at_time=30)   # ngắt 25 giây (tab dừng chia sẻ rồi chọn lại)
    w.pause()
    w.push(pcm(1), at_time=60)   # tiếp tục sau tạm dừng
    w.close()
    starts = sorted(round(r[1], 2) for r in received)
    assert starts == [3.0, 28.0, 59.0]


def test_browser_only_capture_websocket_reconnect_and_export(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeWhisper())
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Thu âm chọn tab'}).json()['id']
        r = c.post(f'/api/meetings/{mid}/start', json={'mic': None, 'system': None, 'browser_sources': ['browser1']})
        assert r.status_code == 200, r.text
        # Cổng khác 8765 vẫn phải được chấp nhận khi Origin khớp Host.
        headers = {'origin': 'http://localhost:9000', 'host': 'localhost:9000'}
        with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=headers) as ws:
            ws.send_json({'rate': 16000, 'label': 'Tab · Meet'})
            assert ws.receive_json()['ready']
            ws.send_bytes(pcm(1, 2000))
            ws.send_bytes(pcm(1, 3000))
            ws.send_text('ping')
            assert ws.receive_json()['pong']
            m = wait_for(c, mid, lambda m: m['browser_connected'] == ['browser1'])
            assert m['browser_connected'] == ['browser1']
            assert m['levels']['browser1'] > 0
        # Kết nối rớt => đoạn dở được chốt, nguồn được phép nối lại.
        m = wait_for(c, mid, lambda m: len(m['chunks']) >= 1)
        assert len(m['chunks']) == 1, m['chunks']
        with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=headers) as ws:
            ws.send_json({'rate': 16000})
            assert ws.receive_json()['ready']
            ws.send_bytes(pcm(1, 2500))
        # Nguồn 2 được thêm giữa chừng dù không khai báo lúc bắt đầu.
        with c.websocket_connect(f'/api/meetings/{mid}/browser/browser2', headers=headers) as ws:
            ws.send_json({'rate': 48000})
            assert ws.receive_json()['ready']
            ws.send_bytes(pcm(0.5, 1000, 48000))
        m = wait_for(c, mid, lambda m: len(m['chunks']) >= 3)
        assert sorted(json.loads(m['sources_json'])['browser_sources']) == ['browser1', 'browser2']
        c.post(f'/api/meetings/{mid}/stop').raise_for_status()
        m = wait_for(c, mid, lambda m: all(ch['state'] == 'done' for ch in m['chunks']))
        assert {ch['source'] for ch in m['chunks']} == {'browser1', 'browser2'}
        assert m['status'] == 'finished'
        md = c.get(f'/api/meetings/{mid}/export.md').text
        assert 'Âm thanh cuộc họp' in md and 'sources: [browser1, browser2]' in md
        assert c.get(f'/api/meetings/{mid}/audio/browser1').status_code == 200
        c.delete(f'/api/meetings/{mid}').raise_for_status()


def test_websocket_rejects_foreign_origin_and_duplicate_connection(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeWhisper())
    from starlette.websockets import WebSocketDisconnect
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Bảo vệ'}).json()['id']
        c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1']}).raise_for_status()
        bad = {'origin': 'http://evil.example', 'host': '127.0.0.1:8765'}
        try:
            with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=bad) as ws:
                ws.receive_json()
            raise AssertionError('Origin lạ phải bị từ chối')
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        good = {'origin': 'http://127.0.0.1:8765', 'host': '127.0.0.1:8765'}
        with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=good) as ws:
            ws.send_json({'rate': 16000})
            assert ws.receive_json()['ready']
            try:
                with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=good) as ws2:
                    ws2.receive_json()
                raise AssertionError('Kết nối trùng nguồn phải bị từ chối')
            except WebSocketDisconnect as exc:
                assert exc.code == 4001
        c.post(f'/api/meetings/{mid}/stop').raise_for_status()
        c.delete(f'/api/meetings/{mid}').raise_for_status()


def test_pause_blocks_browser_audio_and_resume_continues(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeWhisper())
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Tạm dừng'}).json()['id']
        c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1']}).raise_for_status()
        headers = {'origin': 'http://127.0.0.1:8765', 'host': '127.0.0.1:8765'}
        with c.websocket_connect(f'/api/meetings/{mid}/browser/browser1', headers=headers) as ws:
            ws.send_json({'rate': 16000})
            ws.receive_json()
            ws.send_bytes(pcm(1))
            ws.send_text('pause')
            c.post(f'/api/meetings/{mid}/pause').raise_for_status()
            m = wait_for(c, mid, lambda m: len(m['chunks']) == 1 and m['status'] == 'paused')
            assert len(m['chunks']) == 1
            ws.send_bytes(pcm(1))  # dữ liệu gửi trong lúc tạm dừng phải bị bỏ qua
            ws.send_text('ping'); ws.receive_json()
            assert len(c.get(f'/api/meetings/{mid}').json()['chunks']) == 1
            c.post(f'/api/meetings/{mid}/resume').raise_for_status()
            ws.send_bytes(pcm(1))
            ws.send_text('ping'); ws.receive_json()
        m = wait_for(c, mid, lambda m: len(m['chunks']) == 2)
        assert len(m['chunks']) == 2
        c.post(f'/api/meetings/{mid}/stop').raise_for_status()
        c.delete(f'/api/meetings/{mid}').raise_for_status()
