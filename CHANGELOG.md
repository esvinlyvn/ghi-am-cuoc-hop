# MeetingScribe V1.2 — sửa logic, chạy ổn định cho cuộc họp dài

## V1.2.1
- Sửa lỗi chép lời `open() got an unexpected keyword argument 'metadata_errors'` (PyAV 19): worker tự giải mã WAV bằng FFmpeg thành mảng 16 kHz rồi đưa vào Whisper, không dùng PyAV; đồng thời ghim `av>=11,<19` trong requirements.

## Thu âm tab/cửa sổ (Chrome/Edge)
- Chuyển sang **AudioWorklet** (dự phòng ScriptProcessor): PCM được tạo trên luồng âm thanh, không giật khi tab MeetingScribe ở nền nhiều giờ.
- **Tự nối lại WebSocket** khi rớt; **cho chọn lại nguồn ngay trong lúc ghi** khi tab chia sẻ bị dừng (trước đây phải kết thúc phiên). Nguồn thêm giữa chừng được ghi vào cấu hình phiên.
- Mốc thời gian đoạn tính theo **số mẫu đã nhận** thay vì đồng hồ mỗi gói, nên các đoạn 20 s liên tiếp không lệch; ngắt luồng > 1,5 s mới đặt lại mốc theo đồng hồ thực.
- Thanh tín hiệu của nguồn tab cập nhật tức thì từ trình duyệt; mặc định tắt ô “không phát ra loa” để tránh người dùng tưởng im lặng là lỗi; cảnh báo rõ khi chọn toàn màn hình (ghi toàn bộ hệ thống).
- Wake Lock giữ màn hình khi đang ghi; cảnh báo trước khi đóng tab.
- Nếu nguồn trình duyệt không nối được và không có micro/hệ thống, phiên tự hủy thay vì “ghi” rỗng.

## Thu âm WASAPI / micro
- Mở thiết bị đúng số kênh gốc (loopback nhiều kênh không còn lỗi mở stream), **tự trộn về mono**: dung lượng giảm một nửa (≈ 0,35 GB/giờ/nguồn).
- Tạm dừng thực sự dừng stream (không tích tụ bộ đệm cũ rồi đổ dồn khi tiếp tục).
- Liệt kê micro chỉ qua WASAPI (hết trùng tên MME/DirectSound), chọn thiết bị mặc định đúng.
- Cứu tệp `.partial.wav`: cắt phần lẻ, dọn tệp rỗng; khôi phục bỏ qua đoạn < 0,2 s.
- Ngăn Windows ngủ trong lúc ghi (`SetThreadExecutionState` trên luồng riêng).

## Bộ xử lý
- WebSocket không còn truy vấn SQLite cho **mỗi gói PCM**; trạng thái tạm dừng giữ trong bộ nhớ.
- Kiểm tra Origin theo header Host → chạy được ở cổng khác 8765 (launcher tự đổi cổng khi bận).
- Kết nối SQLite đóng đúng cách (context manager), chỉ mục theo trạng thái đoạn.
- **Lỗi tải mô hình** (chưa có Internet, thiếu CUDA) không còn đánh dấu từng đoạn là lỗi: đoạn giữ trạng thái chờ, giao diện báo nguyên nhân, tự thử lại sau 8 s, đổi mô hình/thiết bị là xóa lỗi. Thêm nút **Thử lại đoạn lỗi** và API `retry-errors`.
- Giải mã tệp nhập chạy trong luồng riêng (không chặn API lúc nhập tệp lớn); thêm `.opus`.
- `lifespan` thay `on_event` (hết cảnh báo deprecated); dừng ghi sạch khi tắt chương trình.
- Chép lại một đoạn không xóa câu đã hiệu đính; thêm xóa câu.
- Kiểm tra dung lượng đĩa: từ chối bắt đầu khi < 1 GB, cảnh báo khi < 3 GB.
- Cảnh báo im lặng chỉ sau 20 s liên tục (không còn báo đỏ mỗi khi micro ngừng nói).

## Xuất dữ liệu
- Markdown schema 1.1: `transcript_status` dùng `complete` / `partial` / `recording`, thêm `segments_in_part`, chú giải nhãn và nguồn, **báo `[MẤT ÂM]`** cho khoảng trống > 3 s của từng nguồn.
- Tên tệp tải về có ngày và tên cuộc họp (mã hóa RFC 5987, không lỗi với dấu tiếng Việt).

## Giao diện
- Chỉ vẽ lại bản chép lời khi dữ liệu đổi (họp 3 giờ với hàng nghìn câu không còn giật mỗi 3 s); tự cuộn theo khi đang ghi.
- Sidebar đánh dấu cuộc họp đang ghi; mở lại trang tự chọn phiên đang ghi; không cho bắt đầu phiên thứ hai.
- Ghi chú lấy mốc hiện tại khi đang ghi, hoặc vị trí đang nghe lại; Enter để thêm.
- Thông báo phân loại (thông tin / cảnh báo), favicon, sửa lỗi click chuyển cuộc họp khi đang ghi không báo gì.

## Bộ hướng dẫn AI (`huong_dan_GPT/`)
- Thêm `01_CAU_HINH_CUSTOM_GPT.md`: cấu hình GPT riêng copy-dán (Instructions < 8000 ký tự, starters, knowledge, kiểm tra).
- Thêm `CAU_LENH_NHANH.md` (ChatGPT/Claude/NotebookLM/Gemini, lệnh cho từng việc) và `MAU_TRANSCRIPT_KIEM_THU.md` (tệp mẫu đúng định dạng, có bẫy 200 → 150 triệu).
- `CHUAN_DU_LIEU_DAU_RA_MD.md` viết lại khớp đúng tệp phần mềm xuất ra.

## Kiểm thử
- `tests/conftest.py`: dùng thư mục dữ liệu tạm cho mọi bài (trước đây bài đầu ghi vào `data/` thật).
- 10 bài: ghi theo số mẫu, khoảng ngắt, nối lại, nguồn thêm giữa chừng, Origin/cổng khác, trùng kết nối, tạm dừng, nhập nhiều tệp, ZIP chia giờ + `[MẤT ÂM]`, lỗi mô hình, chặn bắt đầu phiên thứ hai, khôi phục sau sập.
- Đã chạy thử trong Chromium thật với luồng giả: AudioWorklet → WebSocket → đoạn 20 s → chép lời → xuất → nghe lại → chọn lại nguồn giữa phiên.

---

# V1.1 — chọn lọc 1–2 tab/cửa sổ, chế độ không phát ra loa, thanh tín hiệu từng nguồn.
# V1.0 — micro + WASAPI loopback, Whisper hàng đợi, sửa lời, xuất MD/TXT/ZIP, khôi phục WAV.
