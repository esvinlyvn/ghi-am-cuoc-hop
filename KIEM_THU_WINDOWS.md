# Bài nghiệm thu trên Windows

> Bộ `pytest` chỉ kiểm tra luồng xử lý với âm thanh giả lập. Thu âm WASAPI, hộp thoại chia sẻ của Chrome/Edge và Whisper thật phải thử trên đúng máy sẽ dùng để họp.

## 1. Cài đặt
- [ ] `setup_windows.bat` chạy xong không lỗi; `START_WINDOWS.bat` mở được `http://127.0.0.1:8765` (hoặc cổng khác in trong cửa sổ đen).
- [ ] Ô **Âm thanh máy tính** liệt kê loa/tai nghe đang dùng (tên có “Loopback”); ô **Micro** liệt kê đúng micro, không trùng tên nhiều lần.
- [ ] Mở hai lần `START_WINDOWS.bat`: lần hai tự chuyển cổng 8766 và vẫn ghi được qua tab.

## 2. Nguồn tab (5 phút)
1. Mở một tab YouTube đang phát. Trong MeetingScribe: Âm thanh máy tính = `— Không ghi —`, micro = `— Không ghi —`.
2. **+ Chọn nguồn 1** → chọn *Tab* → tab YouTube → bật *Share tab audio*. Nhãn nguồn phải hiện `Tab · <tên tab>`.
3. **Bắt đầu** → thanh **nguồn 1** nhảy theo tiếng. Thanh hệ thống/micro đứng im (đúng, vì không chọn).
4. Mở tab thứ hai phát tiếng khác, **+ Chọn nguồn 2**; cả hai thanh nhảy độc lập.
5. Trong tab YouTube bấm **Stop sharing** (thanh xanh của Chrome). MeetingScribe phải hiện cảnh báo cam và nút **Chọn nguồn 1** sáng lại; bấm chọn lại → nhãn hiện `· đang ghi`; thanh nhảy tiếp.
6. **Tạm dừng** 30 s (thanh về 0) → **Tiếp tục** → **Kết thúc** sau tổng ≥ 90 s.
7. **Đợi chép lời** về 0. Nghe lại **nguồn chọn 1** và **2**: đúng tiếng từng tab, không lẫn nhau, phần tạm dừng là khoảng lặng, mốc thời gian khớp đồng hồ.
8. Xuất Markdown: có `sources: [browser1, browser2]`, có dòng `[MẤT ÂM]` cho khoảng tạm dừng/dừng chia sẻ.

## 3. Chế độ không phát ra loa
- [ ] Phiên mới, bật ô **Không phát âm thanh tab ra loa**, chọn tab YouTube: loa im nhưng thanh nguồn 1 nhảy; nghe lại có tiếng.
- [ ] Bỏ chọn ô, chọn tab: nhãn không có “không phát ra loa”, loa phát bình thường, vẫn ghi.
- [ ] Mute tab bằng biểu tượng loa trên tab (chuột phải → Mute site): ghi nhận thanh có nhảy hay không, ghi kết quả vào đây: ______

## 4. Âm thanh máy tính + micro (Zoom desktop)
1. Mở Zoom, vào phòng thử, phát tiếng từ máy thứ hai hoặc dùng Test Speaker.
2. Chọn đúng thiết bị Zoom đang phát ở **Âm thanh máy tính**, chọn micro, **Bắt đầu**: cả hai thanh nhảy khi có tiếng tương ứng.
3. Mute Zoom trong Volume Mixer của Windows: thanh hệ thống phải về 0 và sau 20 s có cảnh báo im lặng (đây là hành vi mong đợi, không phải lỗi). Bỏ mute → thanh nhảy lại.
4. Giảm âm lượng tổng về 5 %: ghi kết quả thanh có nhảy không: ______
5. Kết thúc, nghe lại cả hai nguồn, kiểm tra văn bản `LOCAL` (micro) và `UNKNOWN` (hệ thống).

## 5. Khôi phục sau sự cố
1. Phiên mới, ghi ≥ 50 s với bất kỳ nguồn nào.
2. Đóng thẳng cửa sổ đen (chỉ trong bài test).
3. Chạy lại `START_WINDOWS.bat`: phiên hiện **GIÁN ĐOẠN**, các đoạn WAV đã có được chép lời, đoạn cuối dở được cứu.
4. Nghe lại, bấm **Xác nhận kết thúc phiên đã khôi phục**, xuất Markdown có dòng “Cảnh báo phiên ghi”.

## 6. Mô hình chưa tải được
1. Ngắt Internet, phiên mới với mô hình chưa từng tải (ví dụ `base`), ghi 30 s, kết thúc.
2. Giao diện báo “Chưa chép lời được: Không tải được mô hình…”; **Đợi chép lời** không giảm nhưng **Đoạn lỗi** vẫn 0.
3. Bật Internet: trong 10–60 s chép lời tự chạy, không cần bấm gì. (Hoặc đổi mô hình về `small` đã có sẵn.)

## 7. Cuộc họp dài
- [ ] Ghi 2–3 giờ liên tục (tab + micro). Máy không ngủ, thanh tín hiệu còn nhảy ở giờ thứ 2, dung lượng `data/meetings/<id>/audio` tăng ≈ 0,35 GB/giờ/nguồn.
- [ ] Giao diện không giật khi bản chép lời đã có hàng nghìn câu; tìm kiếm hoạt động.
- [ ] Nghe lại tại 00:15, 01:30 và cuối phiên: lệch ≤ 2 s so với đồng hồ.
- [ ] ZIP chia giờ có `PART_01..03`, cùng `meeting_id`, mốc không đặt lại về 00:00:00.
- [ ] Đưa `00_FULL_TRANSCRIPT.md` lên GPT riêng: trả về đủ mục A–I, dẫn mốc đúng.

## Không cam kết trước khi thử trên máy thật
Độ chính xác Whisper với giọng vùng miền/thuật ngữ, tốc độ trên CPU cụ thể, thiết bị USB/Bluetooth đổi giữa phiên, GPU CUDA, khả năng phân biệt người nói từ xa. Bài nào không đạt thì chưa dùng cho cuộc họp quan trọng.
