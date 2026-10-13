"""Lưu luồng PCM 16-bit mono do Chrome/Edge gửi tới qua WebSocket nội bộ.

- Mỗi đoạn WAV được đóng hoàn chỉnh rồi mới đưa vào hàng đợi chép lời.
- Khoảng ngắt luồng (tab tạm dừng chia sẻ, mất kết nối) được giữ thành khoảng trống
  trên trục thời gian: đoạn mới mở lại với mốc tính theo đồng hồ thực của phiên ghi.
- Mốc thời gian của mỗi đoạn được tính theo số mẫu đã nhận kể từ lần mở đoạn gần nhất,
  nên các đoạn liên tiếp không bị lệch do trễ WebSocket.
"""
from __future__ import annotations
import os
import time
import uuid
import wave
import threading
from pathlib import Path

import numpy as np

CHUNK_DURATION = 20.0      # giây mỗi tệp WAV
GAP_RESET_SECONDS = 1.5    # ngắt luồng dài hơn ngưỡng này => mở đoạn mới theo đồng hồ thực
MAX_PACKET_BYTES = 1 << 20


class BrowserPCMWriter:
    def __init__(self, folder, source, sample_rate, started_wall, on_chunk, on_level):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.rate = int(sample_rate)
        if not (8000 <= self.rate <= 192000):
            raise ValueError('Tần số lấy mẫu không hợp lệ')
        self.started_wall = float(started_wall)
        self.on_chunk = on_chunk
        self.on_level = on_level
        self.wav = None
        self.path = None
        self.offset = 0.0          # mốc bắt đầu (giây) của đoạn đang mở
        self.frames = 0            # số mẫu đã ghi vào đoạn đang mở
        self.stream_origin = None  # mốc thời gian phiên tại thời điểm luồng liên tục bắt đầu
        self.stream_frames = 0     # số mẫu nhận được kể từ stream_origin
        self.lock = threading.Lock()
        self.last_feed_at = 0.0
        self.total_frames = 0
        self.closed = False

    # ---- quản lý tệp -------------------------------------------------
    def _open(self, at):
        self.offset = max(0.0, float(at))
        self.path = self.folder / f'{self.source}_{int(self.offset*1000):012d}_{uuid.uuid4().hex[:8]}.partial.wav'
        self.wav = wave.open(str(self.path), 'wb')
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.rate)
        self.frames = 0

    def _rotate(self):
        if self.wav is None:
            return
        self.wav.close()
        if self.frames:
            ready = self.path.with_name(self.path.name.replace('.partial.wav', '.wav'))
            os.replace(self.path, ready)
            self.on_chunk(self.source, self.offset, self.frames / self.rate, ready)
        else:
            self.path.unlink(missing_ok=True)
        self.wav = None
        self.frames = 0

    def _stream_position(self):
        return self.stream_origin + self.stream_frames / self.rate

    # ---- nhận dữ liệu ------------------------------------------------
    def push(self, payload, at_time=None):
        if self.closed:
            raise RuntimeError('Luồng ghi âm đã đóng')
        if len(payload) % 2:
            raise ValueError('Âm thanh PCM phải là 16-bit nguyên khung')
        if len(payload) > MAX_PACKET_BYTES:
            raise ValueError('Gói PCM quá lớn')
        if not payload:
            return
        with self.lock:
            now = time.time() if at_time is None else float(at_time)
            n = len(payload) // 2
            duration = n / self.rate
            gap = (now - self.last_feed_at) if self.last_feed_at else None
            if self.stream_origin is None or (gap is not None and gap > GAP_RESET_SECONDS):
                # Luồng mới hoặc vừa bị ngắt: đóng đoạn dở và đặt lại mốc theo đồng hồ thực.
                self._rotate()
                self.stream_origin = max(0.0, now - self.started_wall - duration)
                self.stream_frames = 0
            if self.wav is None:
                self._open(self._stream_position())
            self.wav.writeframesraw(payload)
            self.frames += n
            self.stream_frames += n
            self.total_frames += n
            self.last_feed_at = now
            vals = np.frombuffer(payload, dtype='<i2').astype('float32')
            rms = float(np.sqrt(np.mean(vals * vals)) / 32768.0)
            self.on_level(self.source, round(min(1.0, rms * 8), 3))
            if self.frames >= int(CHUNK_DURATION * self.rate):
                self._rotate()
                self._open(self._stream_position())

    def pause(self):
        """Đóng đoạn hiện tại; lần nhận kế tiếp sẽ đặt mốc lại theo đồng hồ thực."""
        with self.lock:
            self._rotate()
            self.stream_origin = None
            self.stream_frames = 0
            self.on_level(self.source, 0)

    def close(self):
        with self.lock:
            self._rotate()
            self.closed = True
            self.on_level(self.source, 0)
