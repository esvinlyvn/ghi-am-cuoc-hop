"""Chạy: python -m pytest tests -q (cần pip install pytest httpx)."""
import io
import time
import wave
import zipfile

from fastapi.testclient import TestClient

import app


class FakeSegment:
    start = 0.1
    end = 1.2
    text = 'Cuộc họp thống nhất ngân sách 150 triệu đồng.'


class FakeModel:
    def transcribe(self, *args, **kwargs):
        return iter([FakeSegment()]), None


def make_wav(seconds=2, rate=16000):
    f = io.BytesIO()
    with wave.open(f, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b'\0\0' * int(seconds * rate))
    f.seek(0)
    return f


def wait_for(c, mid, cond, tries=200, pause=0.03):
    m = None
    for _ in range(tries):
        m = c.get(f'/api/meetings/{mid}').json()
        if cond(m):
            return m
        time.sleep(pause)
    return m


def test_upload_transcribe_edit_export(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeModel())
    with TestClient(app.app) as c:
        assert c.get('/').status_code == 200
        assert c.get('/pcm-worklet.js').status_code == 200
        health = c.get('/api/health').json()
        assert health['ok'] and health['version'] == app.VERSION
        mid = c.post('/api/meetings', json={'title': 'Thử nghiệm', 'model': 'small'}).json()['id']
        r = c.post(f'/api/meetings/{mid}/upload', files={'file': ('audio.wav', make_wav(), 'audio/wav')})
        assert r.status_code == 200, r.text
        m = wait_for(c, mid, lambda m: m['chunks'] and m['chunks'][0]['state'] in ('done', 'error'))
        assert m['chunks'][0]['state'] == 'done', m['chunks']
        assert m['status'] == 'imported' and len(m['segments']) == 1
        sid = m['segments'][0]['id']
        c.patch(f'/api/segments/{sid}', json={'text': 'Đã chốt 150 triệu.', 'speaker': 'Chị Lan'}).raise_for_status()
        c.post(f'/api/meetings/{mid}/annotations', json={'kind': 'Quyết định', 'text': 'Tháng tới kiểm tra lại.', 'at_s': 1.0}).raise_for_status()
        md = c.get(f'/api/meetings/{mid}/export.md')
        assert 'filename*=UTF-8' in md.headers['content-disposition']
        md = md.text
        assert 'Đã chốt 150 triệu.' in md and 'speaker: Chị Lan' in md
        assert 'Tháng tới kiểm tra lại.' in md and 'meeting_id' in md
        assert 'transcript_status: complete' in md and 'sources: [imported]' in md
        z = zipfile.ZipFile(io.BytesIO(c.get(f'/api/meetings/{mid}/export-bundle.zip').content))
        assert sorted(z.namelist()) == ['00_FULL_TRANSCRIPT.md', 'PART_01_of_01.md', 'README.txt']
        assert c.get(f'/api/meetings/{mid}/audio/imported').status_code == 200
        # Chép lại đoạn không được làm mất câu đã hiệu đính.
        c.post(f'/api/chunks/{m["chunks"][0]["id"]}/retry').raise_for_status()
        m = wait_for(c, mid, lambda m: m['chunks'][0]['state'] == 'done' and len(m['segments']) == 2)
        texts = sorted(s['text'] for s in m['segments'])
        assert texts == ['Cuộc họp thống nhất ngân sách 150 triệu đồng.', 'Đã chốt 150 triệu.']
        c.delete(f'/api/segments/{sid}').raise_for_status()
        c.delete(f'/api/meetings/{mid}').raise_for_status()
        assert c.get(f'/api/meetings/{mid}').status_code == 404


def test_multi_import_append_bundle_parts_and_gap_report(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeModel())
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Nhiều tệp', 'language': 'auto'}).json()['id']
        for _ in range(2):
            c.post(f'/api/meetings/{mid}/upload', files={'file': ('sample.wav', make_wav(), 'audio/wav')}).raise_for_status()
        m = c.get(f'/api/meetings/{mid}').json()
        assert len(m['chunks']) == 2, m['chunks']
        assert abs(m['chunks'][1]['start_s'] - 2.0) < .03
        assert m['duration'] == 4.0
        # Giả lập cuộc họp dài 2,5 giờ có khoảng mất âm để kiểm tra ZIP chia giờ và báo cáo [MẤT ÂM].
        with app.LOCK, app.dbcon() as db:
            db.execute("UPDATE chunks SET start_s=start_s+9000 WHERE meeting_id=? AND start_s>1", (mid,))
            db.execute('UPDATE meetings SET duration=9002 WHERE id=?', (mid,))
        z = zipfile.ZipFile(io.BytesIO(c.get(f'/api/meetings/{mid}/export-bundle.zip').content))
        names = sorted(z.namelist())
        assert names == ['00_FULL_TRANSCRIPT.md', 'PART_01_of_03.md', 'PART_02_of_03.md', 'PART_03_of_03.md', 'README.txt']
        part3 = z.read('PART_03_of_03.md').decode('utf-8')
        assert 'part_index: 3' in part3 and 'transcript_start: "02:00:00"' in part3
        full = z.read('00_FULL_TRANSCRIPT.md').decode('utf-8')
        assert '[MẤT ÂM] 00:00:02–02:30:02 / imported' in full
        c.delete(f'/api/meetings/{mid}').raise_for_status()


def test_model_load_failure_keeps_chunks_pending_and_reports(monkeypatch):
    def broken(*a):
        raise RuntimeError('không có Internet để tải mô hình')
    monkeypatch.setattr(app, 'get_model', broken)
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Lỗi mô hình'}).json()['id']
        c.post(f'/api/meetings/{mid}/upload', files={'file': ('a.wav', make_wav(1), 'audio/wav')}).raise_for_status()
        m = wait_for(c, mid, lambda m: bool(m['model_error']))
        assert 'không có Internet' in m['model_error']
        assert m['chunks'][0]['state'] in ('pending', 'processing')  # không bị đánh dấu lỗi
        assert c.get('/api/health').json()['model_error']
        # Đổi mô hình/thiết bị xóa lỗi và đánh thức hàng đợi.
        monkeypatch.setattr(app, 'get_model', lambda *a: FakeModel())
        c.patch(f'/api/meetings/{mid}', json={'device': 'cpu', 'model': 'base'}).raise_for_status()
        m = wait_for(c, mid, lambda m: m['chunks'][0]['state'] == 'done', tries=400)
        assert m['chunks'][0]['state'] == 'done' and not m['model_error']
        c.delete(f'/api/meetings/{mid}').raise_for_status()


def test_start_guards_and_retry_errors(monkeypatch):
    monkeypatch.setattr(app, 'get_model', lambda *a: FakeModel())
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Kiểm tra'}).json()['id']
        assert c.post(f'/api/meetings/{mid}/start', json={}).status_code == 400
        assert c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1', 'browser1']}).status_code == 400
        assert c.post(f'/api/meetings/{mid}/stop').status_code == 409
        c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1']}).raise_for_status()
        other = c.post('/api/meetings', json={'title': 'Khác'}).json()['id']
        assert c.post(f'/api/meetings/{other}/start', json={'browser_sources': ['browser2']}).status_code == 409
        assert c.get(f'/api/meetings/{other}').json()['active_session'] == mid
        assert c.delete(f'/api/meetings/{mid}').status_code == 409
        assert c.post(f'/api/meetings/{mid}/upload', files={'file': ('a.wav', make_wav(1), 'audio/wav')}).status_code == 409
        c.post(f'/api/meetings/{mid}/stop').raise_for_status()
        assert c.get('/api/health').json()['active'] is None
        assert c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1']}).status_code == 409
        with app.LOCK, app.dbcon() as db:
            db.execute("INSERT INTO chunks(id,meeting_id,source,start_s,duration,filename,state,error) VALUES('x',?,'browser1',0,1,'missing.wav','error','x')", (mid,))
        assert c.post(f'/api/meetings/{mid}/retry-errors').json()['changed'] == 1
        m = wait_for(c, mid, lambda m: m['chunks'] and m['chunks'][0]['state'] == 'error')
        assert 'Không thấy tệp' in m['chunks'][0]['error']
        c.delete(f'/api/meetings/{mid}').raise_for_status()
        c.delete(f'/api/meetings/{other}').raise_for_status()


def test_wav_salvage_and_recovery_registers_chunks(tmp_path, monkeypatch):
    from audio_engine import salvage_partial_files, downmix_to_mono
    import struct
    p = tmp_path / 'system_000000000000_00112233.partial.wav'
    with wave.open(str(p), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b'\x00\x00' * 16000)
    with p.open('r+b') as f:  # mô phỏng WAV đóng hỏng header, còn khối PCM
        f.seek(4); f.write(b'\x00' * 4)
        f.seek(40); f.write(b'\x00' * 4)
    (tmp_path / 'mic_000000001000_deadbeef.partial.wav').write_bytes(b'')  # tệp rỗng phải bị dọn
    found = salvage_partial_files(tmp_path)
    assert len(found) == 1 and not (tmp_path / 'mic_000000001000_deadbeef.partial.wav').exists()
    with wave.open(str(found[0]), 'rb') as w:
        assert w.getnframes() == 16000
    stereo = struct.pack('<hh', 1000, 3000) * 4
    mono = downmix_to_mono(stereo, 2)
    assert struct.unpack('<4h', mono) == (2000,) * 4

    monkeypatch.setattr(app, 'get_model', lambda *a: FakeModel())
    with TestClient(app.app) as c:
        mid = c.post('/api/meetings', json={'title': 'Khôi phục'}).json()['id']
        c.post(f'/api/meetings/{mid}/start', json={'browser_sources': ['browser1']}).raise_for_status()
        audio = app.folder(mid) / 'audio'
        with wave.open(str(audio / 'browser1_000000012000_abcdef01.partial.wav'), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b'\x00\x00' * 8000)
        # Giả lập sập chương trình: trạng thái còn 'recording' trong DB, tệp còn dở.
        app.CURRENT.update(app.fresh_state())
        app.recovery()
        m = wait_for(c, mid, lambda m: m['status'] == 'interrupted' and len(m['chunks']) == 1)
        assert m['status'] == 'interrupted' and m['chunks'][0]['start_s'] == 12.0
        assert c.post(f'/api/meetings/{mid}/finalize').status_code == 200
        assert c.get(f'/api/meetings/{mid}').json()['status'] == 'finished'
        c.delete(f'/api/meetings/{mid}').raise_for_status()
