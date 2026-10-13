# BỘ HƯỚNG DẪN AI CHO BẢN CHÉP LỜI MEETINGSCRIBE

Phần mềm ghi âm **không** tóm tắt. Việc lập biên bản, tóm tắt, giao việc do AI bên ngoài (ChatGPT, Claude, NotebookLM, Gemini...) làm, dựa trên tệp `.md` bạn xuất ra. Thư mục này chứa mọi thứ để AI "tự biết phải làm gì" ngay khi bạn đính kèm tệp.

| Tệp | Dùng khi nào |
|---|---|
| `01_CAU_HINH_CUSTOM_GPT.md` | Tạo một **GPT riêng** trong ChatGPT (Explore GPTs → Create). Copy từng ô: Tên, Mô tả, Instructions, Conversation starters, tệp Knowledge. Sau đó chỉ cần kéo tệp `.md` vào là GPT tự lập biên bản. |
| `HUONG_DAN_TRO_LY_BIEN_BAN_HOP.md` | Bộ quy tắc đầy đủ. Dán vào **Project Instructions** của Claude Projects / ChatGPT Projects, hoặc tải lên làm tệp Knowledge của GPT riêng. |
| `CAU_LENH_NHANH.md` | Không muốn tạo GPT riêng: câu lệnh dán kèm tệp cho ChatGPT, Claude, NotebookLM, Gemini. Có cả lệnh ngắn cho từng việc (chỉ giao việc, chỉ số liệu, kiểm chứng một câu...). |
| `CHUAN_DU_LIEU_DAU_RA_MD.md` | Mô tả chính xác định dạng tệp `.md` phần mềm xuất ra, để AI (hoặc bạn) hiểu từng dòng metadata và nhãn. Tải lên làm tệp Knowledge thứ hai. |
| `MAU_TRANSCRIPT_KIEM_THU.md` | Tệp mẫu đúng định dạng thật, có bẫy "đề xuất 200 triệu → chốt 150 triệu". Dùng để kiểm tra GPT bạn vừa tạo có trả lời đúng không. |

## Quy trình chuẩn sau mỗi cuộc họp

1. Trong MeetingScribe: chờ **Đợi chép lời = 0**, sửa tên người nói nếu biết, bấm **↓ Xuất Markdown** (cuộc họp > 2 giờ hoặc AI báo tệp quá lớn: bấm **↓ ZIP chia giờ** và gửi lần lượt `PART_01`, `PART_02`...).
2. Mở GPT riêng (hoặc Claude Project) đã cấu hình → kéo tệp `.md` vào → gửi. Không cần gõ gì; AI tự chạy quy trình A–I.
3. Đọc phần **H. Cần xác minh**, mở MeetingScribe, bấm mốc thời gian để nghe lại đoạn nghi ngờ, sửa rồi xuất lại nếu cần.
4. Gõ lệnh theo nhu cầu: `GIAO VIỆC`, `TÓM TẮT`, `QUYẾT ĐỊNH`, `SỐ LIỆU`, `KIỂM CHỨNG <câu>`, `HỎI <câu hỏi>`, `EMAIL`, `XUẤT MD`.

## Bảo mật

Tệp `.md` chứa toàn bộ lời nói trong cuộc họp. Chỉ tải lên dịch vụ AI mà tổ chức của bạn cho phép; với ChatGPT nên tắt "Improve the model for everyone" trong Settings → Data controls, hoặc dùng gói Team/Enterprise. NotebookLM và Claude cũng có chính sách dữ liệu riêng, hãy đọc trước khi dùng cho cuộc họp nhạy cảm.
