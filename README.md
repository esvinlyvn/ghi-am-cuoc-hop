# MeetingScribe V1.2 — Ghi âm và chép lời cuộc họp ngay trên máy

Giao diện HTML chạy trong Chrome/Edge + bộ xử lý Python chạy cục bộ (127.0.0.1). Thu âm từ **1–2 tab trình duyệt được chọn**, **toàn bộ âm thanh máy tính** (Zoom/Teams cài trên máy) và **micro**, lưu WAV từng 20 giây, chép lời bằng Faster Whisper (mô hình chạy tại máy, không gửi âm thanh đi đâu), xuất Markdown chuẩn để đưa lên ChatGPT / Claude / NotebookLM lập biên bản. Không có AI tóm tắt bên trong phần mềm; bộ hướng dẫn cho AI bên ngoài nằm ở thư mục `huong_dan_GPT/`.

Hỗ trợ cuộc họp dài nhiều giờ: âm thanh luôn được ghi xuống đĩa trước, chép lời chạy nền theo hàng đợi, phiên bị ngắt được khôi phục, Markdown có thể chia thành từng phần 1 giờ.

## Cài đặt (Windows 10/11 64-bit)

1. Giải nén vào thư mục có quyền ghi (ví dụ `D:\MeetingScribe`), **không** đặt trong `C:\Program Files`.
2. Cài **Python 3.11 64-bit** từ python.org, tích “Add Python to PATH”. (3.10–3.12 cũng chạy.)
3. Nhấp đúp `setup_windows.bat` (cần Internet, tải khoảng 300 MB thư viện).
4. Nhấp đúp `START_WINDOWS.bat`. Trình duyệt tự mở `http://127.0.0.1:8765`. Nếu cổng bận, chương trình tự chọn cổng kế tiếp và in ra cửa sổ đen.
5. **Giữ cửa sổ đen mở** trong suốt cuộc họp. Phần mềm tự ngăn Windows ngủ khi đang ghi, nhưng đừng gập máy.

Lần đầu bấm ghi, mô hình Whisper (`small` ≈ 480 MB) được tải về; cần Internet một lần. Nếu chưa có mạng, âm thanh vẫn được ghi, chép lời tự chạy khi mô hình tải được.

## Ba cách chọn nguồn âm thanh

| Cách | Khi nào dùng | Lấy được gì |
|---|---|---|
| **Chọn nguồn 1 / 2** (hộp thoại Chrome/Edge) | Họp trên **tab** Chrome/Edge: Google Meet, Zoom web, Teams web, YouTube... | Chỉ tiếng của **đúng tab** đã chọn. Mỗi nguồn là một luồng riêng (`browser1`, `browser2`), không lẫn tiếng Spotify hay ứng dụng khác. |
| **Âm thanh máy tính** (WASAPI loopback) | Zoom/Teams **cài trên máy**, hoặc muốn lấy mọi tiếng đang phát | **Tất cả** âm thanh đi ra loa/tai nghe đã chọn, không tách riêng ứng dụng. |
| **Micro** | Người ngồi tại máy | Luồng `mic` riêng, nhãn `LOCAL`. |

Có thể kết hợp (ví dụ tab Meet + micro). Đừng chọn cả “Âm thanh máy tính” lẫn tab đang phát ra loa: sẽ ghi trùng.

### Hỏi đáp về chọn cửa sổ và tắt tiếng

**Có chọn riêng 1–2 cửa sổ trong khi nhiều cửa sổ cùng phát tiếng không?**
Có, nếu đó là **tab** Chrome/Edge: bấm “Chọn nguồn 1”, chọn mục *Chrome Tab / Tab*, chọn tab họp, bật “Share tab audio”. Lặp lại cho nguồn 2. Chỉ hai tab đó được ghi, tiếng từ nơi khác bị bỏ qua.
Với **cửa sổ ứng dụng cài trên máy** (Zoom desktop, Teams desktop): hộp thoại của Chrome **không cấp âm thanh riêng** cho một cửa sổ trên Windows; phần mềm sẽ báo “KHÔNG cấp luồng âm thanh” và không cho ghi giả. Khi đó có hai lựa chọn:
- Dùng **Âm thanh máy tính** (lấy mọi tiếng) và tắt các ứng dụng gây nhiễu trong lúc họp; hoặc
- Tách bằng Windows: *Settings → System → Sound → Volume mixer* (Win 11) / *App volume and device preferences* (Win 10), đặt **Output** của Zoom sang một thiết bị phát khác (ví dụ tai nghe, hoặc thiết bị ảo như VB-Cable), rồi trong MeetingScribe chọn đúng loopback của thiết bị đó ở ô “Âm thanh máy tính”. Lúc này chỉ Zoom được ghi, YouTube/Spotify phát qua loa không dính vào.

**Đang tắt tiếng (mute) cửa sổ đó trong Windows thì còn ghi được không?**
- Tab Chrome/Edge chọn qua “Chọn nguồn”: bật ô **“Không phát âm thanh tab ra loa khi ghi”** *trước khi* chọn tab. Chrome ngắt tiếng ra loa nhưng vẫn giao luồng âm thanh cho phần mềm; đây là cách đúng để “im lặng mà vẫn ghi”. Tắt tiếng tab bằng biểu tượng loa trên tab thường vẫn ghi được, nhưng **phải nhìn thanh tín hiệu để xác nhận**.
- Ứng dụng bị **mute trong Volume Mixer của Windows** hoặc trong chính Zoom: chế độ **Âm thanh máy tính** ghi **im lặng**, vì loopback lấy tín hiệu sau khi Windows đã trộn và áp âm lượng từng ứng dụng. Giảm âm lượng tổng (master) hoặc rút tai nghe thường vẫn ghi được, nhưng cũng cần kiểm tra. Nguyên tắc: **ghi thử 30 giây, thanh tín hiệu phải nhảy, nghe lại bản WAV** trước khi tin.

## Dùng cho cuộc họp thật

1. Tạo cuộc họp mới (nút ＋), đặt tên.
2. Chọn nguồn theo bảng trên. Phát tiếng thử, bấm **Bắt đầu ghi âm**, xem thanh tín hiệu của từng nguồn nhảy.
3. Trong lúc họp: tab **Ghi chú** để đánh dấu quyết định/việc cần làm tại đúng mốc thời gian (có xuất kèm Markdown). Nếu tab chia sẻ bị dừng (người họp bấm “Stop sharing”, đóng tab), phần mềm cảnh báo; bấm lại **Chọn nguồn** để nối tiếp vào phiên đang ghi, không cần dừng.
4. Bấm **Kết thúc**. Chờ ô **Đợi chép lời** về 0 (máy yếu có thể mất bằng 1/3–1/2 thời lượng họp với mô hình `small` trên CPU).
5. Sửa câu sai, đặt tên người nói ở tab **Người nói**, bấm mốc thời gian để nghe lại đoạn gốc.
6. **↓ Xuất Markdown** (hoặc **↓ ZIP chia giờ** nếu họp dài / AI giới hạn tệp). Đưa tệp lên GPT riêng đã cấu hình theo `huong_dan_GPT/01_CAU_HINH_CUSTOM_GPT.md`, hoặc dán câu lệnh trong `huong_dan_GPT/CAU_LENH_NHANH.md`.

Thông báo và xin phép người tham gia trước khi ghi âm.

## Tính năng

- Hai nguồn tab/cửa sổ riêng biệt qua `getDisplayMedia`, PCM gửi thẳng qua WebSocket nội bộ bằng AudioWorklet (ổn định khi tab ở nền), tự nối lại khi rớt, cho chọn lại nguồn giữa phiên.
- Micro + âm thanh hệ thống qua WASAPI loopback (PyAudioWPatch), ghi mono 16-bit, mỗi đoạn WAV 20 giây có chồng lấn 0,8 s để không mất chữ ở ranh giới.
- Hàng đợi chép lời Faster Whisper (CPU int8 hoặc GPU CUDA), VAD lọc im lặng, tự thử lại khi mô hình chưa tải được, nút “Thử lại đoạn lỗi”.
- Tạm dừng/tiếp tục (mốc thời gian vẫn theo đồng hồ thực), nhập tệp WAV/MP3/M4A/MP4/WebM/OGG/OPUS/FLAC/WMA (ví dụ bản ghi Zoom), nhiều tệp nối tiếp.
- Tìm kiếm, sửa/xóa câu, đổi tên người nói hàng loạt, ghi chú có mốc, nghe lại từng nguồn tại mốc.
- Xuất `.md` chuẩn (metadata YAML, mốc tuyệt đối, báo `[MẤT ÂM]`, trạng thái `complete/partial`), `.txt`, ZIP chia giờ.
- Khôi phục sau sập: tệp `.partial.wav` được sửa header và đưa vào hàng đợi; phiên đánh dấu “GIÁN ĐOẠN” để kiểm tra.
- Cảnh báo: im lặng kéo dài, trình duyệt ngừng gửi dữ liệu, đĩa sắp đầy (từ chối bắt đầu khi còn dưới 1 GB), phiên khác đang ghi.
- Phân biệt người nói tùy chọn bằng pyannote Community-1 (cài riêng, cần Hugging Face token).

## Dung lượng và hiệu năng

- WAV mono 16-bit: 48 kHz ≈ **0,35 GB/giờ/nguồn**; nguồn nhập tệp 16 kHz ≈ 0,12 GB/giờ. Họp 3 giờ với 2 nguồn ≈ 2 GB.
- Whisper `small` trên CPU 4 nhân: xấp xỉ thời gian thực hoặc chậm hơn một chút; `base` nhanh gấp 2–3 lần nhưng kém chính xác tiếng Việt; `medium`/`large-v3` nên dùng GPU.
- Chép lời chỉ dùng tối đa 4 luồng CPU để không làm giật cuộc gọi Zoom đang chạy.

## Lỗi thường gặp

- **Không thấy thiết bị trong “Âm thanh máy tính”**: phát một đoạn tiếng, tải lại trang; kiểm tra `pyaudiowpatch` cài thành công trong cửa sổ setup.
- **Chọn cửa sổ Zoom báo không có âm thanh**: đúng như thiết kế của Chrome trên Windows; dùng “Âm thanh máy tính” hoặc tách thiết bị phát theo hướng dẫn trên.
- **“Chưa chép lời được: Không tải được mô hình”**: cần Internet lần đầu, hoặc chọn GPU nhưng chưa có CUDA/cuDNN → đổi về CPU; âm thanh không mất.
- **Thanh tín hiệu đứng ở 0%**: nguồn đang mute (Volume Mixer/Zoom), sai thiết bị loopback (Zoom phát ra tai nghe Bluetooth nhưng chọn loa), hoặc tab chưa bật “Share tab audio”.
- **Mất kết nối ghi nguồn**: cửa sổ đen bị đóng. Mở lại `START_WINDOWS.bat`; phiên cũ được đánh dấu gián đoạn, có thể xuất những gì đã ghi.
- **Cổng 8765 bận**: chương trình tự chuyển cổng 8766…; xem địa chỉ in trong cửa sổ đen.

## Kiểm thử

```
pip install pytest httpx
python -m pytest tests -q
```

10 bài kiểm thử chạy trên mọi hệ điều hành với mô hình Whisper giả lập (WebSocket → WAV → hàng đợi → Markdown, tạm dừng, nối lại, khôi phục, lỗi mô hình). Thu âm WASAPI và hộp thoại Chrome phải thử trên máy Windows thật theo `KIEM_THU_WINDOWS.md`.

## Cấu trúc

```
setup_windows.bat / START_WINDOWS.bat / INSTALL_SPEAKERS_OPTIONAL.bat
launcher.py            # chọn cổng, mở trình duyệt, chạy uvicorn
app.py                 # API, WebSocket PCM, hàng đợi Whisper, xuất dữ liệu, khôi phục
audio_engine.py        # WASAPI loopback + micro, WAV 20 s, cứu tệp dở
browser_capture.py     # ghi PCM từ trình duyệt, mốc thời gian theo số mẫu
static/                # index.html, main.js, browser-sources.js, pcm-worklet.js, style.css
huong_dan_GPT/         # cấu hình GPT riêng, câu lệnh, chuẩn dữ liệu, tệp mẫu kiểm thử
tests/                 # pytest
data/                  # sinh ra khi dùng: meetings.sqlite3 + WAV từng cuộc họp (không xóa nếu muốn giữ)
```

Thành phần mã nguồn mở: PyAudioWPatch, faster-whisper, FastAPI, Uvicorn, imageio-ffmpeg, NumPy, pyannote (tùy chọn).
