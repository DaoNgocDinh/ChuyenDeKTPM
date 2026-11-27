# Agents tạo đặc tả ứng dụng

### I09 · Requirement

`DesignAgents(store, skills).dispatch(order)` nhận `WorkOrder` từ host I06. Requirement đọc brief, ràng buộc, phản hồi và yêu cầu cũ của đúng run khi sửa. Một lần chỉnh lại JSON được phép khi kết quả sai schema hoặc hợp đồng. Số token từng lần gọi và hash prompt/cấu hình đi kèm bước bàn giao.

Host nhận `Requirements` theo D07, bản Markdown sinh từ chính dữ liệu đó và các câu hỏi làm rõ. Chủ dự án trả lời câu hỏi còn ảnh hưởng đến nghiệp vụ, rồi duyệt đúng phiên bản tại cổng 1. [Hợp đồng](hop-dong-artifact.md) · [Adapter](adapter-model.md)

**Test** · Chạy `uv run --frozen python -m unittest -v tests.test_design_agents`. Đặt `SDLC_LIVE_MODEL=1` để sinh yêu cầu từ brief tiếng Việt qua Neon High.

Một lượt kiểm tra bằng brief tạo và xem việc đã sinh 3 FR, 3 câu hỏi làm rõ, dùng 30.458 token. Các ca còn lại kiểm tra một lần chỉnh JSON, cộng đủ usage và dừng khi lỗi lặp lại.

### I10 · Architecture

`DesignAgents.dispatch(order)` với vai trò `Architecture` chỉ chạy khi phiên bản `requirements` nguồn đã hết câu hỏi làm rõ và được duyệt tại cổng 1 qua `ApprovalService`. Host tự gắn `requirements` `ArtifactRef` (`bound`), khóa stack ứng dụng cố định (`FastAPI`, `React`, `SQLite`) và kiểm tra 100% ánh xạ `FR → component` cùng hợp đồng OpenAPI 3.1.0 (`backend/architecture_view.py`).

Bản thiết kế sinh đồng thời artifact `architecture` (JSON) và tài liệu Markdown `document` (`ADR`, thực thể/quan hệ, sơ đồ Mermaid `FR → component`, OpenAPI, bố cục UI và chiến lược kiểm thử). Nếu yêu cầu mâu thuẫn với stack khóa, model báo qua trường `blocker` để host dừng an toàn ở `needs_human_review` kèm đầy đủ usage.

**Test** · Chạy `uv run --frozen python -m unittest -v tests.test_design_agents tests.test_orchestrator` và `uvx ruff check --select E4,E7,E9,F backend tests`. Đặt `SDLC_LIVE_MODEL=1` để chạy thêm ca live Neon High.

### I11 · Planning

`DesignAgents.dispatch(order)` với vai trò `Planning` nhận đúng cặp `(requirements_ref, architecture_ref)`, xác nhận `requirements` đã duyệt cổng 1 và khớp `architecture.requirements`, rồi tiêm skill `Planning` để sinh `Plan` (`D07`) kèm `bound` khóa chặt hai `ArtifactRef` nguồn.

Bộ kiểm tra [planning.py](../backend/planning.py) (`validate_plan`, `task_order`, `render_plan`) chặn chu trình DAG, dependency không tồn tại, FR thiếu task, task không gắn FR chức năng và đường dẫn tệp ngoài `app/`. Host giữ `architecture` + `plan` tại cổng duyệt 2 nguyên tử (`architecture_plan`) trước khi mở `Dev`, bảo đảm `Planning` không sửa yêu cầu hay đóng task thay `Dev`.

**Test** · Chạy `uv run --frozen python -m unittest -v tests.test_planning tests.test_design_agents tests.test_orchestrator` và `uvx ruff check --select E4,E7,E9,F backend tests`. Đặt `SDLC_LIVE_MODEL=1` để chạy thêm ca live Neon High.
