"""Thu âm micro và âm thanh hệ thống (WASAPI Loopback) trên Windows qua PyAudioWPatch.

- Mỗi nguồn chạy trên một luồng riêng, ghi WAV mono 16-bit theo đoạn 20 giây.
- Đoạn WAV luôn được đóng hoàn chỉnh (header đúng) trước khi đổi tên và đưa vào hàng đợi.
- Tệp `.partial.wav` còn dở sau khi mất điện/tắt đột ngột được cứu khi khởi động lại.
- Module chỉ import pyaudiowpatch bên trong hàm để kiểm thử được trên Linux/macOS.
"""
from __future__ import annotations
import os
import time
import uuid
import wave
import threading
from pathlib import Path

import numpy as np

SAMPLE_FRAMES = 2048
CHUNK_SECONDS = 20
OVERLAP_SECONDS = 0.8


def enumerate_devices():
    import pyaudiowpatch as pa
    with pa.PyAudio() as p:
        sources = {'microphones': [], 'system': []}
        try:
            wasapi_index = p.get_host_api_info_by_type(pa.paWASAPI)['index']
        except Exception:
            wasapi_index = None
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d.get('maxInputChannels', 0) <= 0:
                continue
            entry = {'id': i, 'name': d['name'], 'rate': int(d['defaultSampleRate']),
                     'channels': int(d['maxInputChannels'])}
            if d.get('isLoopbackDevice'):
                sources['system'].append(entry)
            elif wasapi_index is None or d.get('hostApi') == wasapi_index:
                # Chỉ liệt kê micro qua WASAPI để tránh trùng tên (MME/DirectSound liệt kê lại cùng thiết bị).
                sources['microphones'].append(entry)
        if not sources['microphones']:
            for i in range(p.get_device_count()):
                d = p.get_device_info_by_index(i)
                if d.get('maxInputChannels', 0) > 0 and not d.get('isLoopbackDevice'):
                    sources['microphones'].append({'id': i, 'name': d['name'], 'rate': int(d['defaultSampleRate']),
                                                   'channels': int(d['maxInputChannels'])})
        try:
            sources['default_system'] = int(p.get_default_wasapi_loopback()['index'])
        except Exception:
            sources['default_system'] = sources['system'][0]['id'] if sources['system'] else None
        try:
            default_in = p.get_default_input_device_info()
            ids = {m['id'] for m in sources['microphones']}
            sources['default_microphone'] = int(default_in['index']) if int(default_in['index']) in ids else None
            if sources['default_microphone'] is None:
                # Thiết bị mặc định có thể thuộc host API khác; khớp theo tên.
                for m in sources['microphones']:
                    if m['name'] == default_in['name']:
                        sources['default_microphone'] = m['id']
                        break
        except Exception:
            sources['default_microphone'] = None
        if sources['default_microphone'] is None and sources['microphones']:
            sources['default_microphone'] = sources['microphones'][0]['id']
        return sources


def salvage_partial_files(folder: Path):
    """Cứu các tệp WAV còn mở lúc chương trình hoặc Windows bị tắt bất ngờ."""
    recovered = []
    for file in folder.glob('*.partial.wav'):
        try:
            length = file.stat().st_size
            if length <= 44:
                file.unlink(missing_ok=True)
                continue
            with file.open('r+b') as f:
                data = f.read(44)
                if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE' or data[36:40] != b'data':
                    continue
                block_align = int.from_bytes(data[32:34], 'little') or 2
                payload = (length - 44) - ((length - 44) % block_align)
                f.seek(4); f.write((payload + 36).to_bytes(4, 'little'))
                f.seek(40); f.write(payload.to_bytes(4, 'little'))
                f.truncate(44 + payload)
            ready = file.with_name(file.name.replace('.partial.wav', '.wav'))
            os.replace(file, ready)
            recovered.append(ready)
        except Exception:
            continue
    return recovered


def downmix_to_mono(raw: bytes, channels: int) -> bytes:
    """Trộn nhiều kênh thành một kênh (int16) để giảm dung lượng; Whisper chỉ cần mono."""
    if channels <= 1:
        return raw
    arr = np.frombuffer(raw, dtype='<i2')
    usable = len(arr) - (len(arr) % channels)
    if usable <= 0:
        return b''
    mono = arr[:usable].reshape(-1, channels).astype('float32').mean(axis=1)
    return np.clip(mono, -32768, 32767).astype('<i2').tobytes()


class Recorder:
    """Thu các nguồn trong `selections` ({'mic': idx|None, 'system': idx|None})."""

    def __init__(self, session_id, folder, selections, started_wall, on_chunk, on_error, on_level):
        self.session_id = session_id
        self.folder = Path(folder)
        self.selections = selections
        self.started_wall = started_wall
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.on_level = on_level
        self.stop_evt = threading.Event()
        self.pause_evt = threading.Event()
        self.threads = []
        self.closed = False
        self.folder.mkdir(parents=True, exist_ok=True)

    @property
    def active_sources(self):
        return [s for s, d in self.selections.items() if d is not None]

    def start(self):
        for source, dev in self.selections.items():
            if dev is None:
                continue
            t = threading.Thread(target=self._capture, args=(source, int(dev)), daemon=True, name=f'capture_{source}')
            t.start()
            self.threads.append(t)

    def _capture(self, source, device_index):
        import pyaudiowpatch as pa
        p = None
        stream = None
        wav = None
        tmp = None
        total_frames = 0
        rate = None
        start_offset = None
        trailing = b''
        carry = b''
        stream_paused = False
        try:
            p = pa.PyAudio()
            device = p.get_device_info_by_index(device_index)
            rate = int(device['defaultSampleRate'])
            channels = int(device['maxInputChannels'])
            if channels < 1:
                raise RuntimeError('Thiết bị không có kênh âm thanh đầu vào.')
            # Mở đúng số kênh của thiết bị (WASAPI loopback yêu cầu khớp), sau đó tự trộn về mono.
            stream = p.open(format=pa.paInt16, channels=channels, rate=rate,
                            input=True, input_device_index=device_index,
                            frames_per_buffer=SAMPLE_FRAMES)
            keep = int(rate * OVERLAP_SECONDS) * 2
            while not self.stop_evt.is_set():
                if self.pause_evt.is_set():
                    if wav:
                        self._close_chunk(wav, tmp, source, start_offset, total_frames, rate)
                        wav = tmp = None
                        total_frames = 0
                    trailing = b''
                    carry = b''
                    if not stream_paused:
                        try:
                            stream.stop_stream()  # không tích tụ bộ đệm cũ trong lúc tạm dừng
                        except Exception:
                            pass
                        stream_paused = True
                        self.on_level(source, 0.0)
                    time.sleep(0.1)
                    continue
                if stream_paused:
                    stream.start_stream()
                    stream_paused = False
                raw_multi = stream.read(SAMPLE_FRAMES, exception_on_overflow=False)
                if self.stop_evt.is_set() or self.pause_evt.is_set() or not raw_multi:
                    continue
                raw = downmix_to_mono(raw_multi, channels)
                if not raw:
                    continue
                now = time.time()
                frames_in_raw = len(raw) // 2
                if wav is None:
                    start_offset = max(0.0, now - self.started_wall - frames_in_raw / rate - (len(carry) / 2) / rate)
                    token = uuid.uuid4().hex[:8]
                    tmp = self.folder / f'{source}_{int(start_offset*1000):012d}_{token}.partial.wav'
                    wav = wave.open(str(tmp), 'wb')
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
                    if carry:
                        wav.writeframesraw(carry)
                        total_frames += len(carry) // 2
                        carry = b''
                wav.writeframesraw(raw)
                total_frames += frames_in_raw
                trailing = (trailing + raw)[-keep:]
                try:
                    arr = np.frombuffer(raw, dtype='<i2').astype('float32')
                    rms = float(np.sqrt(np.mean(arr * arr)) / 32768.0)
                    self.on_level(source, round(min(1.0, rms * 8.0), 3))
                except Exception:
                    pass
                if total_frames >= CHUNK_SECONDS * rate:
                    self._close_chunk(wav, tmp, source, start_offset, total_frames, rate)
                    carry = trailing
                    wav = tmp = None
                    total_frames = 0
        except Exception as exc:
            self.on_error(source, str(exc))
        finally:
            if wav:
                try:
                    self._close_chunk(wav, tmp, source, start_offset, total_frames, rate)
                except Exception as exc:
                    self.on_error(source, f'Không đóng được tệp WAV: {exc}')
            try:
                if stream:
                    if not stream_paused:
                        stream.stop_stream()
                    stream.close()
            except Exception:
                pass
            try:
                if p:
                    p.terminate()
            except Exception:
                pass
            self.on_level(source, 0.0)

    def _close_chunk(self, wav, path, source, start, frames, rate):
        wav.close()  # cập nhật header WAV trước khi đặt tên tệp hoàn chỉnh
        ready = path.with_name(path.name.replace('.partial.wav', '.wav'))
        os.replace(path, ready)
        if frames:
            self.on_chunk(source, float(start), frames / rate, ready)
        else:
            ready.unlink(missing_ok=True)

    def pause(self):
        self.pause_evt.set()

    def resume(self):
        self.pause_evt.clear()

    def stop(self):
        self.stop_evt.set()
        self.pause_evt.clear()
        for thread in self.threads:
            thread.join(timeout=5.0)
        self.closed = True
