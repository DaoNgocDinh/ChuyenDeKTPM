# D05 · Hợp đồng sáu vai trò

Bản đề xuất để chủ dự án duyệt. P01 xác định sáu vai trò, skill và phạm vi ghi. Host gắn `run_id`, `step_id`, role và phiên bản đầu vào khi gọi. Các vai trò cùng dùng model được cấu hình cho run.

| Vai trò và skill | Đầu vào bắt buộc | Sản phẩm bàn giao | Hành động và điểm dừng |
| --- | --- | --- | --- |
| Orchestrator · `workflow-coordination` | Brief, stage, checkpoint, quota, artifact đã duyệt hoặc kết quả từ bước trước | Đề xuất giao việc, yêu cầu duyệt hoặc tóm tắt kèm tham chiếu | Đọc metadata qua host. Host kiểm tra trạng thái, phiên bản, dependency và quota trước khi ghi sự kiện. Chờ chủ dự án tại hai cổng. |
| Requirement · `requirements-analysis` | Brief, ràng buộc, phản hồi, phiên bản cũ khi sửa | Tác nhân, FR/NFR, tiêu chí nghiệm thu, câu hỏi, bản Markdown và JSON cùng phiên bản | Đọc brief/artifact trong run. Còn câu hỏi ảnh hưởng hành vi thì trả câu hỏi. Đủ dữ liệu thì chuyển chủ dự án duyệt phiên bản. |
| Architecture · `architecture-design` | Requirements đúng phiên bản đã duyệt và stack | ADR, thành phần, lược đồ dữ liệu, API, bố cục UI, chiến lược test và ánh xạ FR | Đọc artifact nguồn. Gặp yêu cầu mâu thuẫn thì báo blocker cho Requirement. Host kiểm tra đủ FR trước khi chuyển Planning. |
| Planning · `task-planning` | Requirements đã duyệt và architecture đúng phiên bản | DAG gồm task, FR, dependency, tệp dự kiến, test và điều kiện xong | Đọc hai artifact. Thiếu FR, task trỏ nhầm hoặc có chu trình thì trả lỗi. Plan hợp lệ và architecture đi cùng nhau vào cổng duyệt thứ hai. |
| Dev · `implementation` | Task sẵn sàng hoặc được giao sửa, cặp artifact đã duyệt, commit đầu vào, bug nếu có | Patch, tệp thay đổi, commit sau ghi và kết quả tự kiểm tra | Đọc mã và artifact cùng run, đề xuất patch trong `app/`, gọi suite được cấp. Host áp patch/checkpoint. Bàn giao commit cho Tester. |
| Tester · `testing-review` | FR, tiêu chí, task, diff, commit sau patch | Test trong `tests_dev/`, report của runner, review và bug có bước tái hiện khi thất bại | Đọc app, ghi test phát triển và báo cáo. Suite cho kết quả gắn commit. Trả bug mã cho Dev, lỗi yêu cầu cho Requirement, lỗi thiết kế cho Architecture. |

### Ví dụ kiểm tra bàn giao

Với task A1 chống tiêu đề rỗng, Dev chuyển `task_id=T1`, `requirement_ids=[FR-title]`, commit đầu và commit sau sửa cho Tester. Tester chạy suite trên commit sau sửa, lưu report và mô tả đầu vào chuỗi rỗng, kết quả mong đợi và thực tế. Khi test đỏ do mã, host giao Dev cùng task và bug. Sau patch mới, Tester chạy lại ca đỏ cùng regression trên commit mới. Hết ba lần sửa sau lần triển khai đầu, host chuyển việc cho người duyệt. Đây là fixture thiết kế để kiểm tra hợp đồng.

Nếu báo cáo thuộc run khác hoặc commit cũ, host từ chối bàn giao. Khi lỗi thuộc yêu cầu, chủ dự án duyệt phiên bản thay thế và xem lại đầu ra bị ảnh hưởng trước khi Dev chạy tiếp.

**Cách test** · Đi theo task T1 ở trên với ba đầu vào: báo cáo đúng commit, báo cáo sai commit và yêu cầu thay đổi tiêu chí. Kết quả mong đợi lần lượt là chuyển đúng vai trò, từ chối, và chờ duyệt lại. So tên sáu skill với bảng 5.2 trong [P01](ke-hoach.md).
