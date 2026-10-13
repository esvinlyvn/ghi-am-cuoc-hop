# BẮT ĐẦU TRƯỚC CUỘC HỌP (5 phút)

1. Chạy `START_WINDOWS.bat` (lần đầu phải chạy `setup_windows.bat` trước). Trang mở ở `http://127.0.0.1:8765` trên **Chrome hoặc Edge**. Giữ cửa sổ đen mở.
2. Bấm **＋** tạo cuộc họp thử. Chọn nguồn:
   - Họp trên tab Chrome (Meet/Zoom web): đặt **Âm thanh máy tính** = `— Không ghi nguồn này —`, bấm **+ Chọn nguồn 1**, chọn *Tab* → tab họp → bật **Chia sẻ âm thanh tab**. Thêm **Chọn nguồn 2** nếu cần tab thứ hai. Chọn micro nếu bạn nói tại máy.
   - Zoom/Teams cài trên máy: chọn đúng thiết bị phát Zoom đang dùng ở **Âm thanh máy tính** (tai nghe hay loa), chọn micro.
3. Muốn tab không phát tiếng ra loa: bật **Không phát âm thanh tab ra loa khi ghi** *trước* khi bấm Chọn nguồn. Chỉ tin khi nhãn nguồn hiện `không phát ra loa` và thanh tín hiệu vẫn nhảy.
4. Phát tiếng mẫu, bấm **Bắt đầu ghi âm**, nhìn thanh tín hiệu của từng nguồn nhảy ít nhất 30 giây, bấm **Kết thúc**. Ở **Nghe lại & xuất dữ liệu** chọn nguồn vừa ghi → **Tạo bản nghe**. **Phải nghe thấy tiếng thật.** Chờ **Đợi chép lời** về 0 và thấy chữ xuất hiện.
5. Cuộc họp thật: tạo **phiên mới**, ghi đến hết. Trong lúc họp dùng tab **Ghi chú** đánh dấu quyết định. Nếu thấy cảnh báo màu cam (tab dừng chia sẻ, mất kết nối), bấm lại **Chọn nguồn** để nối tiếp. Kết thúc → chờ chép lời xong → **Xuất Markdown** → đưa lên AI theo `huong_dan_GPT/00_DOC_TRUOC.md`.

## Nếu chọn cửa sổ Zoom mà báo “KHÔNG cấp luồng âm thanh”

Đó là giới hạn của Chrome trên Windows với cửa sổ ứng dụng cài máy. Đừng cố ghi nguồn đó. Dùng **Âm thanh máy tính** (ghi mọi tiếng đang phát, tắt YouTube/Spotify trong lúc họp) hoặc tách Zoom sang thiết bị phát riêng bằng Volume Mixer rồi chọn loopback của thiết bị đó (xem README).

## Mute và ghi âm

- Mute ứng dụng trong **Volume Mixer của Windows** hoặc trong Zoom → chế độ **Âm thanh máy tính** ghi im lặng.
- Muốn im lặng mà vẫn ghi: dùng tab Chrome + ô **Không phát âm thanh tab ra loa**, hoặc đeo tai nghe.
- Không suy đoán: ghi thử → thanh tín hiệu → nghe lại.

## Trước cuộc họp dài (2–5 giờ)

- Ổ đĩa còn ít nhất **1 GB cho mỗi giờ** (2 nguồn). Giao diện từ chối bắt đầu khi còn dưới 1 GB.
- Cắm sạc; phần mềm tự ngăn máy ngủ nhưng không ngăn khi gập máy.
- Chọn mô hình `small` (CPU) hoặc `medium`/`large-v3` (GPU). Chép lời có thể hoàn tất sau khi họp xong; âm thanh không mất.
- Nên bật thêm ghi dự phòng của nền tảng họp nếu được phép.
