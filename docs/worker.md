# I05 · Hàng đợi và worker

`Queue(database).enqueue(project_id, key, config, budget)` ghi job bền dùng cùng cơ chế idempotency của I02. API trả run ID rồi kết thúc request. Worker mở DB bằng connection riêng. `claim()` kiểm run đang chạy và lấy job đầu hàng đợi bằng một transaction ghi. Lease mang project, run và token do host cấp. Gửi hai job liên tiếp sẽ để job thứ hai ở queued đến khi worker nhả job thứ nhất.

`Worker(queue, handler).run_forever(stop_event)` chạy trong tiến trình worker. Handler nhận `(lease, lost_event)`, kiểm tra việc mất quyền sở hữu trước tác động bên ngoài và trả một sự kiện hợp lệ của D08 như `request_approval` hoặc `final_checks_passed`. Worker gia hạn lease song song với handler. Các bước thực thi gọi `queue.start_step` để ghi operation ID, phiên bản đầu vào và checkpoint trước khi tác động. `queue.finish_step` nhận kết quả của chính operation đó và lưu checkpoint sau tác động. Dùng token trong mọi transaction ghi metadata của worker.

Nếu worker chết, lần claim kế tiếp sau khi hết lease sẽ ghi trạng thái pending_recovery và event, giữ nguyên checkpoint cùng bước đã bắt đầu. I20 dùng các bằng chứng này để đối chiếu thao tác chưa rõ kết quả. Việc đóng UI hoặc API không ảnh hưởng dữ liệu hàng đợi. I06 cung cấp handler điều phối theo giai đoạn.

**Cách test** · Chạy `python -m unittest tests.test_worker -v`. Mong đợi 5 ca đạt, gồm tranh chấp giữa bốn connection, checkpoint trước/sau, worker chết ở tiến trình riêng, heartbeat khi handler đang bận và lỗi chưa rõ kết quả.
