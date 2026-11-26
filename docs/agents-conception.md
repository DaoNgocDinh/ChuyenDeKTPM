# Agents tạo đặc tả ứng dụng

### I09 · Requirement

`DesignAgents(store, skills).dispatch(order)` nhận `WorkOrder` từ host I06. Requirement đọc brief, ràng buộc, phản hồi và yêu cầu cũ của đúng run khi sửa. Một lần chỉnh lại JSON được phép khi kết quả sai schema hoặc hợp đồng. Số token từng lần gọi và hash prompt/cấu hình đi kèm bước bàn giao.

Host nhận `Requirements` theo D07, bản Markdown sinh từ chính dữ liệu đó và các câu hỏi làm rõ. Chủ dự án trả lời câu hỏi còn ảnh hưởng đến nghiệp vụ, rồi duyệt đúng phiên bản tại cổng 1. [Hợp đồng](hop-dong-artifact.md) · [Adapter](adapter-model.md)

**Test** · Chạy `uv run --frozen python -m unittest -v tests.test_design_agents`. Đặt `SDLC_LIVE_MODEL=1` để sinh yêu cầu từ brief tiếng Việt qua Neon High.

Một lượt kiểm tra bằng brief tạo và xem việc đã sinh 3 FR, 3 câu hỏi làm rõ, dùng 30.458 token. Các ca còn lại kiểm tra một lần chỉnh JSON, cộng đủ usage và dừng khi lỗi lặp lại.
