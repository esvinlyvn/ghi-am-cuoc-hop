"""MeetingScribe — ghi âm / chép lời cuộc họp cục bộ. Không có AI tóm tắt bên trong.

Chỉ lắng nghe 127.0.0.1; dữ liệu nằm trong thư mục `data/`. Các tệp âm thanh không được
phục vụ trực tiếp, chỉ qua API ghép đoạn để nghe lại.
"""
from __future__ import annotations
import contextlib
import datetime as dt
import io
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import wave
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from audio_engine import Recorder, enumerate_devices, salvage_partial_files
from browser_capture import BrowserPCMWriter

VERSION = '1.2.1'
ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('MEETING_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
SESSIONS = DATA / 'meetings'
SESSIONS.mkdir(exist_ok=True)
DB = DATA / 'meetings.sqlite3'
LOCK = threading.RLock()
WAKE = threading.Event()
MODEL_CACHE = {'name': None, 'device': None, 'model': None, 'error': '', 'loading': False}
JOBS = {}
ALLOWED_IMPORTS = {'.wav', '.mp3', '.m4a', '.mp4', '.aac', '.flac', '.ogg', '.webm', '.wma', '.opus'}
MODELS = ('tiny', 'base', 'small', 'medium', 'large-v3', 'turbo')
SOURCES = ('mic', 'system', 'browser1', 'browser2', 'imported')
BROWSER_SOURCES = ('browser1', 'browser2')
MIN_FREE_BYTES = 1 << 30           # từ chối bắt đầu khi còn dưới 1 GB
SILENCE_WARN_SECONDS = 20          # cảnh báo khi một nguồn im lặng liên tục quá lâu
FEED_WARN_SECONDS = 5              # cảnh báo khi trình duyệt ngừng gửi dữ liệu


def fresh_state():
    return {'recorder': None, 'session': None, 'started_wall': None, 'paused': False,
            'levels': {s: 0.0 for s in SOURCES}, 'last_signal': {}, 'errors': {},
            'browser_writers': {}, 'browser_connected': {}, 'browser_sources': []}


CURRENT = fresh_state()


# ----------------------------------------------------------------------------- tiện ích
def utcnow():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def localnow():
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def sid():
    return str(uuid.uuid4())


@contextlib.contextmanager
def dbcon():
    c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA busy_timeout=30000')
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with dbcon() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT, ended_at TEXT, status TEXT NOT NULL DEFAULT 'ready',
            language TEXT NOT NULL DEFAULT 'vi', model TEXT NOT NULL DEFAULT 'small',
            device TEXT NOT NULL DEFAULT 'cpu', sources_json TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
            duration REAL NOT NULL DEFAULT 0, paused_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, source TEXT NOT NULL,
            start_s REAL NOT NULL, duration REAL NOT NULL, filename TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(meeting_id) REFERENCES meetings(id)
        );
        CREATE TABLE IF NOT EXISTS segments (
            id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, chunk_id TEXT NOT NULL,
            source TEXT NOT NULL, start_s REAL NOT NULL, end_s REAL NOT NULL,
            speaker TEXT NOT NULL DEFAULT 'UNKNOWN', text TEXT NOT NULL,
            edited INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id)
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_meeting ON chunks(meeting_id,start_s);
        CREATE INDEX IF NOT EXISTS idx_chunks_state ON chunks(state);
        CREATE INDEX IF NOT EXISTS idx_segments_meeting ON segments(meeting_id,start_s);
        CREATE TABLE IF NOT EXISTS annotations (
            id TEXT PRIMARY KEY, meeting_id TEXT NOT NULL, at_s REAL NOT NULL,
            kind TEXT NOT NULL, text TEXT NOT NULL
        );
        ''')


def meeting_or_404(mid):
    with dbcon() as c:
        row = c.execute('SELECT * FROM meetings WHERE id=?', (mid,)).fetchone()
    if not row:
        raise HTTPException(404, 'Không tìm thấy cuộc họp')
    return dict(row)


def folder(mid):
    # mid chỉ được lấy từ SQLite, không nhận path tuỳ ý.
    return SESSIONS / mid


def disk_free_bytes():
    try:
        return shutil.disk_usage(DATA).free
    except Exception:
        return None


def register_chunk(mid, source, start_s, duration, file):
    chunk_id = sid()
    with LOCK, dbcon() as c:
        c.execute('INSERT INTO chunks(id,meeting_id,source,start_s,duration,filename) VALUES(?,?,?,?,?,?)',
                  (chunk_id, mid, source, max(0.0, float(start_s)), float(duration), Path(file).name))
        c.execute('UPDATE meetings SET duration=max(duration,?) WHERE id=?', (float(start_s) + float(duration), mid))
    WAKE.set()
    return chunk_id


def recovery():
    """Đánh dấu các phiên bị ngắt và đăng ký các tệp thu âm đã cứu."""
    with LOCK, dbcon() as c:
        c.execute("UPDATE meetings SET status='interrupted',error='Ứng dụng dừng trong lúc ghi. Đã khôi phục các đoạn âm thanh có thể đọc.' WHERE status IN ('recording','paused')")
        c.execute("UPDATE chunks SET state='pending' WHERE state='processing'")
        meetings = [r['id'] for r in c.execute('SELECT id FROM meetings').fetchall()]
    for mid in meetings:
        audio = folder(mid) / 'audio'
        if not audio.exists():
            continue
        salvage_partial_files(audio)
        with dbcon() as c:
            known = {r[0] for r in c.execute('SELECT filename FROM chunks WHERE meeting_id=?', (mid,))}
        for file in audio.glob('*.wav'):
            if file.name in known:
                continue
            m = re.match(r'^(mic|system|browser1|browser2)_(\d{12})_[a-f0-9]+\.wav$', file.name)
            if not m:
                continue
            try:
                with wave.open(str(file), 'rb') as w:
                    duration = w.getnframes() / w.getframerate()
                if duration > 0.2:
                    register_chunk(mid, m[1], int(m[2]) / 1000, duration, file)
                else:
                    file.unlink(missing_ok=True)
            except Exception:
                pass
    WAKE.set()


def elapsed_time(data):
    if CURRENT['session'] == data['id'] and data['status'] in ('recording', 'paused') and CURRENT['started_wall']:
        # Tính từ lúc bấm bắt đầu, gồm cả khoảng tạm dừng, để khớp mốc thời gian thực của cuộc họp.
        return max(float(data['duration']), time.time() - CURRENT['started_wall'])
    return float(data['duration'])


def update_error(mid, source, msg):
    CURRENT['errors'][source] = msg
    with LOCK, dbcon() as c:
        c.execute('UPDATE meetings SET error=? WHERE id=?', (f'{source}: {msg}', mid))


def on_level(source, level):
    CURRENT['levels'][source] = level
    if level > 0.004:
        CURRENT['last_signal'][source] = time.time()


def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ----------------------------------------------------------------------------- giữ máy thức
class KeepAwake:
    """Ngăn Windows ngủ trong lúc ghi (SetThreadExecutionState chỉ hiệu lực trên luồng gọi)."""

    def __init__(self):
        self.stop_evt = threading.Event()
        self.thread = None

    def start(self):
        if sys.platform != 'win32' or self.thread:
            return
        self.stop_evt.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name='KeepAwake')
        self.thread.start()

    def _run(self):
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            while not self.stop_evt.wait(30):
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        finally:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:
                pass

    def stop(self):
        self.stop_evt.set()
        self.thread = None


KEEP_AWAKE = KeepAwake()


# ----------------------------------------------------------------------------- giải mã tệp nhập
def decode_to_wav_chunks(file, target_dir, mid, source='imported', start_offset=0.0):
    """Giải mã tệp nhập thành WAV 16 kHz mono, chia đoạn 20 giây có chồng lấn 0,8 s."""
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = uuid.uuid4().hex[:8]
    intermediate = target_dir / f'__decode_{stamp}.wav'
    cmd = [ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(file),
           '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(intermediate)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=None)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-1300:] or 'FFmpeg không thể giải mã tệp đầu vào.')
        created = 0
        offset = float(start_offset)
        with wave.open(str(intermediate), 'rb') as src:
            rate = src.getframerate()
            frames = src.getnframes()
            per_chunk = 20 * rate
            overlap = int(0.8 * rate)
            cursor = 0
            while cursor < frames:
                src.setpos(cursor)
                raw = src.readframes(per_chunk)
                if not raw:
                    break
                out = target_dir / f'{source}_{stamp}_{created:05d}.wav'
                with wave.open(str(out), 'wb') as dst:
                    dst.setnchannels(1); dst.setsampwidth(2); dst.setframerate(rate)
                    dst.writeframes(raw)
                duration = len(raw) / (2 * rate)
                register_chunk(mid, source, offset + cursor / rate, duration, out)
                created += 1
                if cursor + per_chunk >= frames:
                    break
                cursor += per_chunk - overlap
        if not created:
            raise RuntimeError('Không tìm thấy âm thanh có thể chuyển văn bản.')
        return created, offset + frames / rate
    finally:
        intermediate.unlink(missing_ok=True)


def create_meeting(title, model='small', device='cpu', language='vi', status='ready'):
    mid = sid()
    folder(mid).joinpath('audio').mkdir(parents=True, exist_ok=True)
    with LOCK, dbcon() as c:
        c.execute('INSERT INTO meetings(id,title,created_at,status,model,device,language) VALUES(?,?,?,?,?,?,?)',
                  (mid, title.strip() or 'Cuộc họp chưa đặt tên', utcnow(), status, model, device, language))
    return mid


# ----------------------------------------------------------------------------- Whisper
def get_model(name, device):
    actual_device = device if device in ('cpu', 'cuda') else 'cpu'
    if MODEL_CACHE['model'] is not None and MODEL_CACHE['name'] == name and MODEL_CACHE['device'] == actual_device:
        return MODEL_CACHE['model']
    from faster_whisper import WhisperModel
    MODEL_CACHE['loading'] = True
    try:
        compute = 'int8_float16' if actual_device == 'cuda' else 'int8'
        cpu_threads = max(2, min(4, (os.cpu_count() or 4) // 2))
        mdl = WhisperModel(name, device=actual_device, compute_type=compute, cpu_threads=cpu_threads)
    finally:
        MODEL_CACHE['loading'] = False
    MODEL_CACHE.update({'name': name, 'device': actual_device, 'model': mdl})
    return mdl


def load_audio_16k(path):
    """Giải mã WAV thành mảng float32 16 kHz mono bằng FFmpeg.

    Tự giải mã thay vì để faster-whisper dùng PyAV: tránh lỗi "open() got an unexpected
    keyword argument 'metadata_errors'" khi PyAV đổi API (PyAV 19) và không phụ thuộc phiên bản.
    """
    proc = subprocess.run([ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-i', str(path),
                           '-f', 's16le', '-ac', '1', '-ar', '16000', '-'], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError('FFmpeg không đọc được đoạn âm thanh: ' + (proc.stderr.decode('utf-8', 'ignore')[-400:] or 'không có dữ liệu'))
    import numpy as np
    return np.frombuffer(proc.stdout, dtype='<i2').astype('float32') / 32768.0


def transcribe_worker():
    while True:
        ch = None
        try:
            with LOCK, dbcon() as c:
                row = c.execute('''SELECT ch.*,m.model,m.device,m.language FROM chunks ch
                   JOIN meetings m ON m.id=ch.meeting_id WHERE ch.state='pending'
                   ORDER BY ch.rowid LIMIT 1''').fetchone()
                if row:
                    c.execute("UPDATE chunks SET state='processing',error='' WHERE id=?", (row['id'],))
            if row is None:
                WAKE.wait(1.25)
                WAKE.clear()
                continue
            ch = dict(row)
            wavfile = folder(ch['meeting_id']) / 'audio' / ch['filename']
            if not wavfile.is_file():
                raise RuntimeError('Không thấy tệp âm thanh ' + str(wavfile.name))
            try:
                model = get_model(ch['model'], ch['device'])
            except Exception as exc:
                # Lỗi tải mô hình (chưa có Internet, thiếu CUDA...) không phải lỗi của đoạn âm thanh:
                # giữ đoạn ở trạng thái chờ, báo lỗi chung và thử lại sau.
                MODEL_CACHE['error'] = f'Không tải được mô hình "{ch["model"]}" trên {ch["device"]}: {str(exc)[:600]}'
                with LOCK, dbcon() as c:
                    c.execute("UPDATE chunks SET state='pending' WHERE id=?", (ch['id'],))
                time.sleep(8)
                continue
            MODEL_CACHE['error'] = ''
            audio = load_audio_16k(wavfile)
            segments, _ = model.transcribe(audio, language=(ch['language'] if ch['language'] in ('vi', 'en') else None),
                                           task='transcribe', beam_size=4, vad_filter=True,
                                           vad_parameters={'min_silence_duration_ms': 600},
                                           condition_on_previous_text=False)
            with dbcon() as c:
                prior_end = c.execute('SELECT max(end_s) FROM segments WHERE meeting_id=? AND source=? AND chunk_id<>? AND start_s<?',
                                      (ch['meeting_id'], ch['source'], ch['id'], ch['start_s'] + ch['duration'])).fetchone()[0]
            prior_end = float(prior_end or 0)
            output = []
            for seg in segments:
                phrase = seg.text.strip()
                if not phrase:
                    continue
                abs_start = ch['start_s'] + float(seg.start)
                abs_end = ch['start_s'] + float(seg.end)
                # Bỏ câu nằm trọn trong phần chồng lấn đã được đoạn trước chép.
                if prior_end > ch['start_s'] and abs_end <= prior_end + 0.05:
                    continue
                output.append((sid(), ch['meeting_id'], ch['id'], ch['source'], abs_start, abs_end,
                               ('LOCAL' if ch['source'] == 'mic' else 'UNKNOWN'), phrase))
            with LOCK, dbcon() as c:
                # Một đoạn có thể được xử lý lại sau lỗi: không nhân đôi dữ liệu, giữ câu đã hiệu đính.
                c.execute('DELETE FROM segments WHERE chunk_id=? AND edited=0', (ch['id'],))
                c.executemany('INSERT INTO segments(id,meeting_id,chunk_id,source,start_s,end_s,speaker,text) VALUES(?,?,?,?,?,?,?,?)', output)
                c.execute("UPDATE chunks SET state='done',error='' WHERE id=?", (ch['id'],))
        except Exception as exc:
            if ch:
                with LOCK, dbcon() as c:
                    c.execute('UPDATE chunks SET state=?,error=? WHERE id=?', ('error', str(exc)[:1200], ch['id']))
            time.sleep(0.4)


# ----------------------------------------------------------------------------- xuất dữ liệu
def hms(t):
    t = int(max(0, t))
    return f'{t//3600:02}:{(t//60)%60:02}:{t%60:02}'


def yaml_str(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') + '"'


def dump_md(m, part_start=None, part_end=None, part_index=1, total_parts=1):
    mid = m['id']
    with dbcon() as c:
        rows = [dict(r) for r in c.execute('SELECT * FROM segments WHERE meeting_id=? ORDER BY start_s,source,id', (mid,))]
        ann = [dict(r) for r in c.execute('SELECT * FROM annotations WHERE meeting_id=? ORDER BY at_s', (mid,))]
        chunks = [dict(r) for r in c.execute('SELECT * FROM chunks WHERE meeting_id=? ORDER BY start_s', (mid,))]
    pending = sum(ch['state'] in ('pending', 'processing') for ch in chunks)
    errors = [ch for ch in chunks if ch['state'] == 'error']
    complete = m['status'] in ('finished', 'imported') and bool(chunks) and pending == 0 and not errors
    end_bound = part_end if part_end is not None else float('inf')
    if part_start is not None:
        rows = [s for s in rows if part_start <= s['start_s'] < end_bound]
        ann = [a for a in ann if part_start <= a['at_s'] < end_bound]
    srcs = sorted({ch['source'] for ch in chunks})
    date = (m['started_at'] or m['created_at'])[:10]
    status_word = 'complete' if complete else ('recording' if m['status'] in ('recording', 'paused') else 'partial')
    out = [
        '---', 'document_type: meeting_transcript', 'schema_version: "1.1"',
        f'meeting_id: {yaml_str(mid)}', f'meeting_title: {yaml_str(m["title"])}',
        f'recording_date: "{date}"', 'recording_timezone: "Asia/Ho_Chi_Minh"',
        f'recording_duration: "{hms(m["duration"])}"',
        f'transcript_start: "{hms(part_start or 0)}"',
        f'transcript_end: "{hms(part_end if part_end is not None else m["duration"])}"',
        f'part_index: {part_index}', f'total_parts: {total_parts}',
        f'transcript_status: {status_word}',
        'speaker_labels_verified: false',
        f'segments_in_part: {len(rows)}',
        f'sources: [{", ".join(srcs)}]',
        '---', '', '# BẢN CHÉP LỜI CUỘC HỌP', '',
        '## Thông tin', '', f'- Cuộc họp: {m["title"]}', f'- Ngày ghi: {date}',
        f'- Thời lượng ghi: {hms(m["duration"])}',
        f'- Phần {part_index}/{total_parts}: từ {hms(part_start or 0)} đến {hms(part_end if part_end is not None else m["duration"])}',
        '- Bản chép lời do công cụ nhận dạng tiếng nói tạo ra; tên riêng, con số và thuật ngữ có thể sai.',
        '- Nhãn người nói: `LOCAL` = micro tại máy; `UNKNOWN` = chưa xác định; tên khác do người dùng đặt.',
        '- Nguồn âm thanh: `mic` = micro; `system` = toàn bộ âm thanh máy tính; `browser1`/`browser2` = tab/cửa sổ được chọn; `imported` = tệp nhập.',
        f'- Đoạn chưa xử lý: {pending}; đoạn lỗi: {len(errors)}',
    ]
    if m['error']:
        out.append(f'- Cảnh báo phiên ghi: {m["error"]}')
    if not complete:
        out.append('- CẢNH BÁO: Bản xuất CHƯA HOÀN TẤT. Không được coi là toàn bộ nội dung cuộc họp.')
    out.extend(['', '## Bản chép lời (nguyên văn nhận dạng, có thể đã được người dùng hiệu đính)', ''])
    if not rows:
        out.extend(['[Chưa có đoạn văn bản nào trong khoảng thời gian này.]', ''])
    for s in rows:
        out.extend([f'[{hms(s["start_s"])} --> {hms(s["end_s"])}] [speaker: {s["speaker"]}] [source: {s["source"]}]', s['text'], ''])
    out.extend(['## Ghi chú thủ công', ''])
    if not ann:
        out.append('(Không có)')
    for a in ann:
        out.append(f'- [{hms(a["at_s"])}] [{a["kind"]}] {a["text"]}')
    out.extend(['', '## Tình trạng nguồn ghi', ''])
    if not chunks:
        out.append('- Chưa có đoạn âm thanh.')
    gaps = detect_gaps(chunks)
    for g in gaps:
        out.append(f'- [MẤT ÂM] {hms(g[0])}–{hms(g[1])} / {g[2]}: không có dữ liệu âm thanh trong khoảng này.')
    for ch in chunks:
        if ch['state'] == 'error':
            out.append(f'- [LỖI CHÉP LỜI] {hms(ch["start_s"])}–{hms(ch["start_s"]+ch["duration"])} / {ch["source"]}: {ch["error"]}')
        elif ch['state'] in ('processing', 'pending'):
            out.append(f'- [CHỜ CHÉP LỜI] {hms(ch["start_s"])}–{hms(ch["start_s"]+ch["duration"])} / {ch["source"]}')
    if not gaps and not any(ch['state'] != 'done' for ch in chunks) and chunks:
        out.append('- Mọi đoạn âm thanh đã được chép lời; không phát hiện khoảng mất dữ liệu > 3 giây.')
    out.append('- Âm thanh gốc được lưu cục bộ, không đính kèm trong tệp Markdown.')
    out.append('')
    return '\n'.join(out)


def detect_gaps(chunks, threshold=3.0):
    """Tìm khoảng trống > threshold giây giữa các đoạn của cùng một nguồn."""
    gaps = []
    by_source = {}
    for ch in chunks:
        by_source.setdefault(ch['source'], []).append(ch)
    for source, items in by_source.items():
        items.sort(key=lambda x: x['start_s'])
        cursor = None
        for ch in items:
            if cursor is not None and ch['start_s'] - cursor > threshold:
                gaps.append((cursor, ch['start_s'], source))
            cursor = max(cursor or 0, ch['start_s'] + ch['duration'])
    return sorted(gaps)


def combine_audio(mid, source):
    m = meeting_or_404(mid)
    if m['status'] in ('recording', 'paused'):
        raise HTTPException(409, 'Hãy kết thúc ghi âm trước khi tạo tệp nghe liền mạch.')
    with dbcon() as c:
        chunks = [dict(x) for x in c.execute('SELECT * FROM chunks WHERE meeting_id=? AND source=? ORDER BY start_s', (mid, source))]
    if not chunks:
        raise HTTPException(404, 'Không có âm thanh cho nguồn này.')
    cache = folder(mid) / f'combined_{source}.wav'
    newest = max((folder(mid) / 'audio' / ch['filename']).stat().st_mtime for ch in chunks if (folder(mid) / 'audio' / ch['filename']).exists())
    if cache.is_file() and cache.stat().st_mtime >= newest:
        return cache
    target = cache.with_suffix('.working')
    cursor = 0
    with wave.open(str(target), 'wb') as w:
        w.setnchannels(1); w.setframerate(16000); w.setsampwidth(2)
        for ch in chunks:
            path = folder(mid) / 'audio' / ch['filename']
            if not path.exists():
                continue
            begin = int(ch['start_s'] * 16000)
            if begin > cursor:
                gap = begin - cursor
                while gap:
                    block = min(gap, 160000)
                    w.writeframesraw(b'\0\0' * block)
                    gap -= block
                cursor = begin
            proc = subprocess.run([ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-i', str(path),
                                   '-f', 's16le', '-ac', '1', '-ar', '16000', '-'], capture_output=True)
            if proc.returncode != 0:
                raise HTTPException(500, 'Không đọc được đoạn âm thanh.')
            data = proc.stdout
            # Bỏ phần chồng lấn khi ghép để phát lại không bị lặp.
            overlap = max(0, cursor - begin)
            if overlap:
                data = data[overlap * 2:]
            w.writeframesraw(data)
            cursor += len(data) // 2
    os.replace(target, cache)
    return cache


# ----------------------------------------------------------------------------- ứng dụng
@contextlib.asynccontextmanager
async def lifespan(_app):
    init_db()
    recovery()
    threading.Thread(target=transcribe_worker, daemon=True, name='WhisperJobWorker').start()
    yield
    rec = CURRENT.get('recorder')
    if rec:
        try:
            rec.stop()
        except Exception:
            pass
    for writer in list(CURRENT['browser_writers'].values()):
        try:
            writer.close()
        except Exception:
            pass
    KEEP_AWAKE.stop()


app = FastAPI(title='MeetingScribe', docs_url=None, redoc_url=None, lifespan=lifespan)


def audio_warnings(data):
    """Cảnh báo khi nguồn không có dữ liệu; không báo trong lúc tạm dừng hay vừa bắt đầu."""
    mid = data['id']
    if CURRENT['session'] != mid or data['status'] != 'recording':
        return []
    now = time.time()
    if now - (CURRENT['started_wall'] or now) < 10:
        return []
    messages = []
    for key in CURRENT['browser_sources']:
        writer = CURRENT['browser_writers'].get(key)
        if writer is None:
            messages.append(f'{key}: trình duyệt chưa kết nối (tab chia sẻ đã dừng hoặc trang bị đóng). Bấm "Chọn nguồn" để nối lại.')
        elif not writer.last_feed_at or now - writer.last_feed_at > FEED_WARN_SECONDS:
            messages.append(f'{key}: không nhận dữ liệu âm thanh trong {FEED_WARN_SECONDS} giây qua.')
        elif now - CURRENT['last_signal'].get(key, CURRENT['started_wall']) > SILENCE_WARN_SECONDS:
            messages.append(f'{key}: im lặng liên tục hơn {SILENCE_WARN_SECONDS} giây; kiểm tra nguồn có bị tắt tiếng không.')
    rec = CURRENT.get('recorder')
    for key in (rec.active_sources if rec else []):
        if CURRENT['errors'].get(key):
            messages.append(f'{key}: lỗi thiết bị — {CURRENT["errors"][key]}')
        elif now - CURRENT['last_signal'].get(key, CURRENT['started_wall']) > SILENCE_WARN_SECONDS:
            messages.append(f'{key}: im lặng liên tục hơn {SILENCE_WARN_SECONDS} giây; phát thử hoặc kiểm tra thiết bị.')
    free = disk_free_bytes()
    if free is not None and free < 2 * MIN_FREE_BYTES:
        messages.append(f'Ổ đĩa chỉ còn {free/2**30:.1f} GB trống. Hãy giải phóng dung lượng.')
    return messages


def origin_allowed(websocket: WebSocket):
    origin = websocket.headers.get('origin', '')
    if not origin:
        return True
    host = websocket.headers.get('host', '')
    allowed = {f'http://{host}'}
    port = host.rsplit(':', 1)[-1] if ':' in host else ''
    for name in ('127.0.0.1', 'localhost', '[::1]'):
        allowed.add(f'http://{name}:{port}' if port else f'http://{name}')
    return origin in allowed


@app.websocket('/api/meetings/{mid}/browser/{source}')
async def browser_stream(websocket: WebSocket, mid: str, source: str):
    if source not in BROWSER_SOURCES or CURRENT['session'] != mid or not origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    if CURRENT['browser_connected'].get(source):
        await websocket.close(code=4001)  # nguồn này đang có kết nối khác
        return
    CURRENT['browser_connected'][source] = True
    await websocket.accept()
    writer = None
    try:
        header = await websocket.receive_json()
        rate = header.get('rate')
        if not isinstance(rate, int) or not 8000 <= rate <= 192000:
            await websocket.close(code=1003)
            return
        writer = BrowserPCMWriter(folder(mid) / 'audio', source, rate, CURRENT['started_wall'],
                                  lambda so, start, dur, path: register_chunk(mid, so, start, dur, path), on_level)
        CURRENT['browser_writers'][source] = writer
        if source not in CURRENT['browser_sources']:
            CURRENT['browser_sources'].append(source)
            with LOCK, dbcon() as c:
                row = c.execute('SELECT sources_json FROM meetings WHERE id=?', (mid,)).fetchone()
                cfg = json.loads((row['sources_json'] if row else '') or '{}')
                cfg['browser_sources'] = sorted(set(cfg.get('browser_sources', [])) | {source})
                c.execute('UPDATE meetings SET sources_json=? WHERE id=?', (json.dumps(cfg), mid))
        CURRENT['errors'].pop(source, None)
        await websocket.send_json({'ready': True, 'label': header.get('label', '')})
        while CURRENT['session'] == mid:
            packet = await websocket.receive()
            if packet['type'] == 'websocket.disconnect':
                break
            text = packet.get('text')
            if text is not None:
                if text == 'pause':
                    writer.pause()
                elif text == 'ping':
                    await websocket.send_json({'pong': True, 'level': CURRENT['levels'].get(source, 0)})
                continue
            raw = packet.get('bytes')
            if raw and not writer.closed and not CURRENT['paused']:
                writer.push(raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        update_error(mid, source, repr(exc))
    finally:
        if writer:
            writer.close()
            if CURRENT['browser_writers'].get(source) is writer:
                CURRENT['browser_writers'].pop(source, None)
        CURRENT['browser_connected'].pop(source, None)
        CURRENT['levels'][source] = 0


@app.get('/api/health')
def health():
    try:
        import faster_whisper  # noqa: F401
        whisper = True
    except Exception:
        whisper = False
    free = disk_free_bytes()
    return {'ok': True, 'version': VERSION, 'platform': sys.platform, 'whisper': whisper,
            'data_dir': str(DATA), 'active': CURRENT['session'],
            'disk_free_gb': round(free / 2**30, 2) if free is not None else None,
            'model_error': MODEL_CACHE['error'], 'model_loading': MODEL_CACHE['loading'],
            'model_loaded': MODEL_CACHE['name']}


@app.get('/api/devices')
def devices():
    empty = {'microphones': [], 'system': [], 'default_system': None, 'default_microphone': None}
    if sys.platform != 'win32':
        return {**empty, 'error': 'Thu thiết bị âm thanh trực tiếp (WASAPI) chỉ có trên Windows. Trên hệ điều hành khác vẫn dùng được chế độ chọn tab/cửa sổ của Chrome/Edge.'}
    try:
        return enumerate_devices()
    except Exception as e:
        return {**empty, 'error': f'Không liệt kê được thiết bị âm thanh: {e}'}


class MeetingCreate(BaseModel):
    title: str = Field('Cuộc họp mới', max_length=200)
    model: str = 'small'
    device: str = 'cpu'
    language: str = 'vi'


@app.post('/api/meetings')
def new_meeting(p: MeetingCreate):
    if p.model not in MODELS:
        raise HTTPException(400, 'Model không hợp lệ')
    if p.device not in ('cpu', 'cuda'):
        raise HTTPException(400, 'Thiết bị xử lý không hợp lệ')
    mid = create_meeting(p.title, p.model, p.device, p.language if p.language in ('vi', 'en', 'auto') else 'vi')
    return {'id': mid}


@app.get('/api/meetings')
def list_meetings():
    with dbcon() as c:
        rows = c.execute('''SELECT m.id,m.title,m.created_at,m.started_at,m.status,m.duration,
             (SELECT COUNT(*) FROM segments s WHERE s.meeting_id=m.id) AS segment_count,
             (SELECT COUNT(*) FROM chunks ch WHERE ch.meeting_id=m.id AND ch.state IN ('pending','processing')) AS pending_count,
             (SELECT COUNT(*) FROM chunks ch WHERE ch.meeting_id=m.id AND ch.state='error') AS error_count
             FROM meetings m ORDER BY m.created_at DESC''').fetchall()
    return [dict(r) for r in rows]


@app.get('/api/meetings/{mid}')
def get_meeting(mid: str):
    m = meeting_or_404(mid)
    with dbcon() as c:
        m['segments'] = [dict(r) for r in c.execute('SELECT * FROM segments WHERE meeting_id=? ORDER BY start_s,source,id', (mid,))]
        m['annotations'] = [dict(r) for r in c.execute('SELECT * FROM annotations WHERE meeting_id=? ORDER BY at_s', (mid,))]
        m['chunks'] = [dict(r) for r in c.execute('SELECT id,source,start_s,duration,state,error FROM chunks WHERE meeting_id=? ORDER BY start_s', (mid,))]
    active = CURRENT['session'] == mid
    m['elapsed'] = elapsed_time(m)
    m['levels'] = dict(CURRENT['levels']) if active else {s: 0 for s in SOURCES}
    m['audio_warnings'] = audio_warnings(m) if active else []
    m['browser_connected'] = sorted(CURRENT['browser_writers'].keys()) if active else []
    m['active_session'] = CURRENT['session']
    m['model_error'] = MODEL_CACHE['error']
    m['model_loading'] = MODEL_CACHE['loading']
    free = disk_free_bytes()
    m['disk_free_gb'] = round(free / 2**30, 2) if free is not None else None
    return m


class MeetingPatch(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    device: Optional[str] = None
    language: Optional[str] = None


@app.patch('/api/meetings/{mid}')
def patch_meeting(mid: str, p: MeetingPatch):
    m = meeting_or_404(mid)
    allowed = {}
    if p.title is not None:
        allowed['title'] = p.title.strip()[:200] or m['title']
    if p.model is not None and p.model in MODELS:
        allowed['model'] = p.model
    if p.device in ('cpu', 'cuda'):
        allowed['device'] = p.device
    if p.language in ('vi', 'en', 'auto'):
        allowed['language'] = p.language
    if allowed:
        with LOCK, dbcon() as c:
            c.execute('UPDATE meetings SET ' + ','.join(f'{k}=?' for k in allowed) + ' WHERE id=?', (*allowed.values(), mid))
        if 'model' in allowed or 'device' in allowed:
            MODEL_CACHE['error'] = ''
            WAKE.set()
    return {'ok': True}


class StartCapture(BaseModel):
    mic: Optional[int] = None
    system: Optional[int] = None
    browser_sources: list[str] = Field(default_factory=list, max_length=2)


@app.post('/api/meetings/{mid}/start')
def start_capture(mid: str, p: StartCapture):
    if sys.platform != 'win32' and (p.mic is not None or p.system is not None):
        raise HTTPException(400, 'Thu thiết bị âm thanh trực tiếp chỉ hỗ trợ Windows; chọn nguồn tab/cửa sổ vẫn khả dụng.')
    if p.mic is None and p.system is None and not p.browser_sources:
        raise HTTPException(400, 'Chưa chọn nguồn âm thanh.')
    if len(set(p.browser_sources)) != len(p.browser_sources) or any(x not in BROWSER_SOURCES for x in p.browser_sources):
        raise HTTPException(400, 'Chỉ hỗ trợ hai nguồn tab/cửa sổ riêng biệt.')
    free = disk_free_bytes()
    if free is not None and free < MIN_FREE_BYTES:
        raise HTTPException(507, f'Ổ đĩa chỉ còn {free/2**30:.2f} GB. Cần ít nhất 1 GB trống để bắt đầu ghi.')
    with LOCK:
        if CURRENT['recorder'] is not None:
            raise HTTPException(409, 'Một cuộc họp khác đang ghi âm. Hãy kết thúc phiên đó trước.')
        m = meeting_or_404(mid)
        if m['status'] != 'ready':
            raise HTTPException(409, 'Cuộc họp này đã bắt đầu hoặc đã kết thúc. Hãy tạo phiên mới để ghi âm.')
        if p.mic is not None or p.system is not None:
            try:
                devices_now = enumerate_devices()
            except Exception as e:
                raise HTTPException(500, f'Không đọc được danh sách thiết bị: {e}')
            valid = {'mic': {d['id'] for d in devices_now['microphones']}, 'system': {d['id'] for d in devices_now['system']}}
            if p.mic is not None and p.mic not in valid['mic']:
                raise HTTPException(400, 'Micro không hợp lệ hoặc không còn tồn tại. Tải lại trang để cập nhật danh sách.')
            if p.system is not None and p.system not in valid['system']:
                raise HTTPException(400, 'Thiết bị âm thanh hệ thống không còn tồn tại. Tải lại trang để cập nhật danh sách.')
        selections = {'mic': p.mic, 'system': p.system}
        saved_sources = {**selections, 'browser_sources': list(p.browser_sources)}
        t = time.time()
        CURRENT.update(fresh_state())
        CURRENT.update({'session': mid, 'started_wall': t, 'browser_sources': list(p.browser_sources)})
        rec = Recorder(mid, folder(mid) / 'audio', selections, t,
                       lambda source, start, dur, path: register_chunk(mid, source, start, dur, path),
                       lambda source, msg: update_error(mid, source, msg), on_level)
        CURRENT['recorder'] = rec
        try:
            rec.start()
        except Exception:
            CURRENT.update(fresh_state())
            raise
        with dbcon() as c:
            c.execute("UPDATE meetings SET status='recording',started_at=?,sources_json=?,error='' WHERE id=?",
                      (localnow(), json.dumps(saved_sources), mid))
    KEEP_AWAKE.start()
    return {'ok': True, 'started_wall': t}


@app.post('/api/meetings/{mid}/pause')
def pause_capture(mid: str):
    with LOCK:
        if CURRENT['session'] != mid or not CURRENT['recorder']:
            raise HTTPException(409, 'Không có phiên ghi đang hoạt động.')
        CURRENT['paused'] = True
        CURRENT['recorder'].pause()
        for writer in list(CURRENT['browser_writers'].values()):
            writer.pause()
        with dbcon() as c:
            c.execute("UPDATE meetings SET status='paused' WHERE id=?", (mid,))
    return {'ok': True}


@app.post('/api/meetings/{mid}/resume')
def resume_capture(mid: str):
    with LOCK:
        if CURRENT['session'] != mid or not CURRENT['recorder']:
            raise HTTPException(409, 'Không có phiên ghi đang hoạt động.')
        CURRENT['paused'] = False
        CURRENT['recorder'].resume()
        now = time.time()
        for key in SOURCES:
            CURRENT['last_signal'][key] = now  # không báo im lặng ngay sau khi tiếp tục
        with dbcon() as c:
            c.execute("UPDATE meetings SET status='recording' WHERE id=?", (mid,))
    return {'ok': True}


@app.post('/api/meetings/{mid}/stop')
def stop_capture(mid: str):
    with LOCK:
        if CURRENT['session'] != mid or not CURRENT['recorder']:
            raise HTTPException(409, 'Không có phiên ghi đang hoạt động.')
        duration = max(0.0, time.time() - CURRENT['started_wall'])
        rec = CURRENT['recorder']
        CURRENT['recorder'] = None  # chặn pause/stop lần hai trong lúc đang dừng
        writers = list(CURRENT['browser_writers'].values())
    # Dừng ngoài LOCK: luồng thu cần LOCK để đăng ký đoạn WAV cuối cùng.
    rec.stop()
    for writer in writers:
        writer.close()
    with LOCK:
        with dbcon() as c:
            c.execute("UPDATE meetings SET status='finished',ended_at=?,duration=max(duration,?) WHERE id=?",
                      (localnow(), duration, mid))
        CURRENT.update(fresh_state())
    KEEP_AWAKE.stop()
    WAKE.set()
    return {'ok': True}


@app.post('/api/meetings/{mid}/finalize')
def finalize_recovered(mid: str):
    m = meeting_or_404(mid)
    if m['status'] != 'interrupted':
        raise HTTPException(409, 'Chỉ hoàn tất phiên được khôi phục sau sự cố.')
    with LOCK, dbcon() as c:
        c.execute("UPDATE meetings SET status='finished' WHERE id=?", (mid,))
    return {'ok': True}


@app.post('/api/meetings/{mid}/upload')
async def upload_audio(mid: str, file: UploadFile = File(...)):
    m = meeting_or_404(mid)
    if m['status'] not in ('ready', 'finished', 'interrupted', 'imported'):
        raise HTTPException(409, 'Kết thúc ghi âm trước khi nhập tệp.')
    extension = Path(file.filename or '').suffix.lower()
    if extension not in ALLOWED_IMPORTS:
        raise HTTPException(400, 'Định dạng không hỗ trợ. Dùng WAV, MP3, M4A, MP4, AAC, FLAC, OGG, OPUS, WEBM hoặc WMA.')
    target = folder(mid) / 'upload'
    target.mkdir(parents=True, exist_ok=True)
    path = target / (sid() + extension)
    count = 0
    try:
        with path.open('wb') as f:
            while True:
                data = await file.read(4 * 1024 * 1024)
                if not data:
                    break
                count += len(data)
                if count > 3 * 1024 * 1024 * 1024:
                    raise HTTPException(413, 'Tệp vượt 3 GB.')
                f.write(data)
        # Giải mã bằng FFmpeg có thể mất nhiều phút: chạy trong luồng riêng để không chặn API.
        chunks, duration = await run_in_threadpool(decode_to_wav_chunks, path, folder(mid) / 'audio', mid, 'imported', float(m['duration']))
    except Exception as e:
        path.unlink(missing_ok=True)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(400, f'Không nhập được âm thanh: {e}')
    with LOCK, dbcon() as c:
        c.execute("UPDATE meetings SET status=CASE WHEN status='ready' THEN 'imported' ELSE status END,duration=max(duration,?) WHERE id=?", (duration, mid))
    WAKE.set()
    return {'ok': True, 'chunks': chunks, 'duration': duration}


class SegmentPatch(BaseModel):
    text: Optional[str] = None
    speaker: Optional[str] = None


def clean_label(value):
    return re.sub(r'[\r\n\[\]]', '', value.strip())[:100]


@app.patch('/api/segments/{segid}')
def patch_segment(segid: str, p: SegmentPatch):
    with dbcon() as c:
        old = c.execute('SELECT * FROM segments WHERE id=?', (segid,)).fetchone()
    if not old:
        raise HTTPException(404, 'Không tìm thấy đoạn văn bản.')
    updates = {}
    if p.text is not None:
        updates['text'] = p.text.strip()[:15000]
    if p.speaker is not None:
        updates['speaker'] = clean_label(p.speaker) or 'UNKNOWN'
    if updates:
        with LOCK, dbcon() as c:
            c.execute('UPDATE segments SET ' + ','.join(f'{k}=?' for k in updates) + ',edited=1 WHERE id=?', (*updates.values(), segid))
    return {'ok': True}


@app.delete('/api/segments/{segid}')
def delete_segment(segid: str):
    with LOCK, dbcon() as c:
        c.execute('DELETE FROM segments WHERE id=?', (segid,))
    return {'ok': True}


class LabelPatch(BaseModel):
    old: str
    new: str


@app.post('/api/meetings/{mid}/rename-speaker')
def rename_speaker(mid: str, p: LabelPatch):
    meeting_or_404(mid)
    label = clean_label(p.new)
    if not label:
        raise HTTPException(400, 'Tên người nói không được trống.')
    with LOCK, dbcon() as c:
        changed = c.execute('UPDATE segments SET speaker=?,edited=1 WHERE meeting_id=? AND speaker=?', (label, mid, p.old)).rowcount
    return {'ok': True, 'changed': changed}


class AnnotationCreate(BaseModel):
    at_s: float = Field(ge=0)
    kind: str = 'Ghi chú'
    text: str = Field(min_length=1, max_length=6000)


@app.post('/api/meetings/{mid}/annotations')
def add_annotation(mid: str, p: AnnotationCreate):
    meeting_or_404(mid)
    aid = sid()
    with LOCK, dbcon() as c:
        c.execute('INSERT INTO annotations(id,meeting_id,at_s,kind,text) VALUES(?,?,?,?,?)',
                  (aid, mid, p.at_s, clean_label(p.kind)[:40] or 'Ghi chú', p.text.strip()))
    return {'id': aid}


@app.delete('/api/annotations/{aid}')
def delete_annotation(aid: str):
    with LOCK, dbcon() as c:
        c.execute('DELETE FROM annotations WHERE id=?', (aid,))
    return {'ok': True}


@app.post('/api/chunks/{cid}/retry')
def retry_chunk(cid: str):
    with LOCK, dbcon() as c:
        ch = c.execute('SELECT id FROM chunks WHERE id=?', (cid,)).fetchone()
        if not ch:
            raise HTTPException(404, 'Không tìm thấy đoạn âm thanh.')
        c.execute("UPDATE chunks SET state='pending',error='' WHERE id=?", (cid,))
    WAKE.set()
    return {'ok': True}


@app.post('/api/meetings/{mid}/retry-errors')
def retry_errors(mid: str):
    meeting_or_404(mid)
    with LOCK, dbcon() as c:
        changed = c.execute("UPDATE chunks SET state='pending',error='' WHERE meeting_id=? AND state='error'", (mid,)).rowcount
    MODEL_CACHE['error'] = ''
    WAKE.set()
    return {'ok': True, 'changed': changed}


def export_name(m, suffix):
    """Tên tệp tải về: ASCII an toàn (giữ dấu tiếng Việt qua filename* theo RFC 5987)."""
    from urllib.parse import quote
    date = (m['started_at'] or m['created_at'])[:10]
    slug = re.sub(r'[^0-9A-Za-zÀ-ỹ]+', '_', m['title']).strip('_')[:40] or 'cuoc_hop'
    return quote(f'MeetingScribe_{date}_{slug}_{m["id"][:8]}{suffix}', safe='')


@app.get('/api/meetings/{mid}/export.md')
def export_md(mid: str):
    m = meeting_or_404(mid)
    return PlainTextResponse(dump_md(m), media_type='text/markdown; charset=utf-8',
                             headers={'Content-Disposition': f"attachment; filename*=UTF-8''{export_name(m, '.md')}"})


@app.get('/api/meetings/{mid}/export.txt')
def export_txt(mid: str):
    m = meeting_or_404(mid)
    return PlainTextResponse(dump_md(m), media_type='text/plain; charset=utf-8',
                             headers={'Content-Disposition': f"attachment; filename*=UTF-8''{export_name(m, '.txt')}"})


@app.get('/api/meetings/{mid}/export-bundle.zip')
def export_bundle(mid: str):
    m = meeting_or_404(mid)
    total = max(float(m['duration']), 1.0)
    count = max(1, math.ceil(total / 3600))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr('00_FULL_TRANSCRIPT.md', dump_md(m))
        for i in range(count):
            st = i * 3600
            en = min((i + 1) * 3600, total)
            z.writestr(f'PART_{i+1:02d}_of_{count:02d}.md', dump_md(m, st, en, i + 1, count))
        z.writestr('README.txt', 'MeetingScribe\nTệp 00_FULL_TRANSCRIPT.md chứa toàn bộ bản chép lời.\n'
                   'Các tệp PART_*.md là từng phần tối đa 1 giờ, cùng meeting_id và mốc thời gian gốc (không đặt lại về 00:00:00).\n'
                   'Nếu AI có giới hạn dung lượng tệp, tải từng phần theo thứ tự.\nKhông có âm thanh gốc trong ZIP này.\n')
    buf.seek(0)
    return StreamingResponse(buf, media_type='application/zip',
                             headers={'Content-Disposition': f"attachment; filename*=UTF-8''{export_name(m, '_BUNDLE.zip')}"})


@app.get('/api/meetings/{mid}/audio/{source}')
def get_audio(mid: str, source: str):
    if source not in SOURCES:
        raise HTTPException(400, 'Nguồn không hợp lệ')
    file = combine_audio(mid, source)
    return FileResponse(file, media_type='audio/wav', filename=file.name, content_disposition_type='inline')


@app.delete('/api/meetings/{mid}')
def delete_meeting(mid: str):
    meeting_or_404(mid)
    if CURRENT['session'] == mid:
        raise HTTPException(409, 'Không thể xóa phiên đang ghi.')
    with LOCK, dbcon() as c:
        c.execute('DELETE FROM segments WHERE meeting_id=?', (mid,))
        c.execute('DELETE FROM annotations WHERE meeting_id=?', (mid,))
        c.execute('DELETE FROM chunks WHERE meeting_id=?', (mid,))
        c.execute('DELETE FROM meetings WHERE id=?', (mid,))
    shutil.rmtree(folder(mid), ignore_errors=True)
    return {'ok': True}


class DiarizeRequest(BaseModel):
    token: str = ''
    source: str = 'system'


@app.post('/api/meetings/{mid}/diarize')
def diarize(mid: str, p: DiarizeRequest):
    meeting_or_404(mid)
    if p.source not in ('system', 'imported', 'browser1', 'browser2'):
        raise HTTPException(400, 'Chỉ phân tích nguồn máy tính, nguồn tab hoặc tệp nhập.')
    if mid in JOBS and JOBS[mid].get('status') == 'running':
        raise HTTPException(409, 'Đã có tác vụ nhận diện đang chạy.')
    if not p.token.strip():
        raise HTTPException(400, 'Nhập mã truy cập Hugging Face đã được cấp quyền Community-1.')

    def run():
        JOBS[mid] = {'status': 'running', 'message': 'Đang đọc mô hình nhận diện người nói...'}
        try:
            from pyannote.audio import Pipeline
            audio = combine_audio(mid, p.source)
            pipeline = Pipeline.from_pretrained('pyannote/speaker-diarization-community-1', token=p.token.strip())
            if pipeline is None:
                raise RuntimeError('Không tải được mô hình. Kiểm tra quyền truy cập Hugging Face.')
            JOBS[mid]['message'] = 'Đang phân tích người nói, có thể mất nhiều thời gian...'
            result = pipeline(str(audio))
            diag = getattr(result, 'exclusive_speaker_diarization', None) or getattr(result, 'speaker_diarization', result)
            turns = [(turn.start, turn.end, label) for turn, _, label in diag.itertracks(yield_label=True)]
            with LOCK, dbcon() as c:
                texts = c.execute('SELECT id,start_s,end_s FROM segments WHERE meeting_id=? AND source=?', (mid, p.source)).fetchall()
                for row in texts:
                    matches = sorted([(max(0, min(row['end_s'], b) - max(row['start_s'], a)), label) for a, b, label in turns], reverse=True)
                    if matches and matches[0][0] > 0:
                        c.execute('UPDATE segments SET speaker=? WHERE id=? AND edited=0', (matches[0][1], row['id']))
            JOBS[mid] = {'status': 'done', 'message': f'Hoàn tất. Đã phân tách {len(set(x[2] for x in turns))} nhãn người nói (cần kiểm tra thủ công).'}
        except Exception as exc:
            JOBS[mid] = {'status': 'error', 'message': str(exc)[:800]}

    threading.Thread(target=run, daemon=True).start()
    return {'ok': True}


@app.get('/api/meetings/{mid}/diarize-status')
def diarize_status(mid: str):
    meeting_or_404(mid)
    return JOBS.get(mid, {'status': 'idle', 'message': ''})


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
