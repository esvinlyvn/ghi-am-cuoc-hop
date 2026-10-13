# CHUẨN DỮ LIỆU MARKDOWN ĐẦU RA CỦA MEETINGSCRIBE
Phiên bản schema: 1.1
Mục đích: mô tả chính xác tệp `.md` mà phần mềm xuất ra, để AI đọc đúng từng dòng, nối nhiều phần, trích dẫn mốc thời gian và biết phần nào thiếu dữ liệu. Tệp transcript **không** chứa kết luận hay tóm tắt của AI.

## I. Quy tắc chung
- UTF-8, phần mở rộng `.md` (bản `.txt` có nội dung y hệt, dành cho nền tảng không nhận `.md`).
- Luôn xuất **toàn bộ** lời thoại theo thứ tự thời gian; không lược bỏ.
- Mốc `HH:MM:SS` tính từ lúc bấm **Bắt đầu ghi** (kể cả khoảng tạm dừng), **không đặt lại** ở mỗi phần.
- Mỗi lượt lời có mốc bắt đầu/kết thúc, nhãn người nói và nguồn âm thanh.
- Từ nghe không rõ (do người dùng hiệu đính) đánh dấu `[KHÔNG RÕ]`; AI không được đoán thêm.
- Mỗi cuộc họp có một `meeting_id` cố định; họp dài được chia `PART_xx` cùng `meeting_id`, khác `part_index`.
- Âm thanh gốc nằm trên máy người dùng, không có trong `.md`.

## II. Khối metadata (YAML, đầu tệp)

| Khóa | Ý nghĩa |
|---|---|
| `document_type` | luôn `meeting_transcript` |
| `schema_version` | `"1.1"` |
| `meeting_id` | mã phiên, giống nhau ở mọi phần của cùng cuộc họp |
| `meeting_title` | tên do người dùng đặt |
| `recording_date` | ngày bắt đầu ghi (giờ địa phương) |
| `recording_duration` | tổng thời lượng phiên |
| `transcript_start` / `transcript_end` | khoảng thời gian tệp này bao phủ (bản đầy đủ: 00:00:00 → hết) |
| `part_index` / `total_parts` | vị trí phần trong bộ ZIP chia giờ (bản đầy đủ: 1/1) |
| `transcript_status` | `complete` = mọi đoạn đã chép xong; `partial` = còn đoạn chờ/lỗi hoặc phiên gián đoạn; `recording` = xuất khi đang ghi |
| `speaker_labels_verified` | luôn `false`: nhãn người nói chưa được xác minh danh tính |
| `segments_in_part` | số lượt lời trong tệp này |
| `sources` | các nguồn có dữ liệu: `mic`, `system`, `browser1`, `browser2`, `imported` |

## III. Nhãn người nói và nguồn

| Giá trị | Nghĩa |
|---|---|
| `speaker: LOCAL` | người nói vào micro tại máy (thường là người dùng) |
| `speaker: UNKNOWN` | chưa xác định (âm thanh từ xa, nhiều người chung một kênh) |
| `speaker: SPEAKER_00`... | nhãn giọng do mô-đun phân biệt người nói (tùy chọn) gán; chưa phải tên thật |
| `speaker: <tên>` | người dùng đã gán tên thủ công |
| `source: mic` | micro |
| `source: system` | toàn bộ âm thanh máy tính (WASAPI loopback) |
| `source: browser1` / `browser2` | tab/cửa sổ do người dùng chọn riêng trong Chrome/Edge |
| `source: imported` | tệp âm thanh/video nhập vào |

Hai nguồn có thể chồng mốc thời gian (ví dụ `mic` và `browser1` cùng lúc): đó là hai người nói ở hai kênh, không phải lặp.

## IV. Ví dụ tệp thật (rút gọn)

```markdown
---
document_type: meeting_transcript
schema_version: "1.1"
meeting_id: "3f2a9c10-…"
meeting_title: "Họp điều hành tháng 10"
recording_date: "2026-10-13"
recording_timezone: "Asia/Ho_Chi_Minh"
recording_duration: "02:31:45"
transcript_start: "00:00:00"
transcript_end: "02:31:45"
part_index: 1
total_parts: 1
transcript_status: complete
speaker_labels_verified: false
segments_in_part: 412
sources: [browser1, mic]
---

# BẢN CHÉP LỜI CUỘC HỌP

## Thông tin

- Cuộc họp: Họp điều hành tháng 10
- Ngày ghi: 2026-10-13
- Thời lượng ghi: 02:31:45
- Phần 1/1: từ 00:00:00 đến 02:31:45
- (các dòng chú giải nhãn và số đoạn chưa xử lý/lỗi)

## Bản chép lời (nguyên văn nhận dạng, có thể đã được người dùng hiệu đính)

[00:00:05 --> 00:00:22] [speaker: LOCAL] [source: mic]
Hôm nay mình kiểm tra lại kế hoạch quý 4.

[00:00:22 --> 00:00:36] [speaker: UNKNOWN] [source: browser1]
Em đề xuất tăng ngân sách quảng cáo lên 200 triệu.

[01:32:10 --> 01:32:26] [speaker: LOCAL] [source: mic]
Chốt 150 triệu cho giai đoạn đầu, cuối tháng mình đánh giá lại.

## Ghi chú thủ công

- [01:32:10] [Quyết định] Chốt 150 triệu đợt 1.

## Tình trạng nguồn ghi

- [MẤT ÂM] 00:39:00–00:39:27 / browser1: không có dữ liệu âm thanh trong khoảng này.
- Âm thanh gốc được lưu cục bộ, không đính kèm trong tệp Markdown.
```

## V. Mục "Ghi chú thủ công"
Dòng `- [HH:MM:SS] [Loại] nội dung`, loại gồm `Ghi chú`, `Quyết định`, `Công việc`, `Cần xác minh`. Đây là ghi chú người dùng gõ lúc họp: độ tin cậy cao hơn transcript tự động; khi mâu thuẫn, AI nêu cả hai và ưu tiên ghi chú.

## VI. Mục "Tình trạng nguồn ghi"
- `[MẤT ÂM] a–b / nguồn`: khoảng trống > 3 giây giữa hai đoạn của cùng nguồn (tab dừng chia sẻ, tạm dừng, mất kết nối). Lời nói trong khoảng này **không có** trong tệp.
- `[LỖI CHÉP LỜI] a–b / nguồn: lý do`: có âm thanh nhưng chưa chép được.
- `[CHỜ CHÉP LỜI] a–b / nguồn`: đang xếp hàng xử lý; tệp xuất sớm.
- Dòng "Cảnh báo phiên ghi" (nếu có) trong mục Thông tin: lỗi thiết bị hoặc phiên bị gián đoạn.

AI phải liệt kê các khoảng này ở mục kiểm tra đầu vào và không suy đoán nội dung trong đó.

## VII. Bộ ZIP chia giờ
`00_FULL_TRANSCRIPT.md` (toàn bộ) + `PART_01_of_N.md`... (mỗi phần tối đa 1 giờ, cùng `meeting_id`, mốc liên tục) + `README.txt`. Khi AI giới hạn dung lượng tệp, gửi lần lượt các `PART` và yêu cầu AI ghép theo `part_index`.
