# I14 · Bảy tool của run qua MCP stdio

Host khởi tạo `step_client(database_path, workspace_root, HostStep, image=...)` cho đúng bước rồi gọi `discover(client)`. Kết quả gồm bản SDK, protocol, phiên bản server, schema và SHA-256 của danh mục. Host gửi `invoke(client, operation_id, tool, arguments)` qua stdio, tách operation ID khỏi đối số model. Server tra lại lease, role và task trong SQLite trước mọi dispatch.

`workspace.list_files/read_file/apply_patch` và `git.status/diff` thao tác trên Git thật. `project.read_artifact` đối chiếu ID/version/hash. `tests.run_suite` lấy profile Docker do host gắn cho run, trả receipt của runner, ID report và phiên bản artifact. Nếu Docker chưa chạy được tiến trình test, receipt ghi đúng trạng thái hạ tầng. Deploy cần code và image I15 để chạy suite.

**Test** · `uv run --frozen python -m unittest tests.test_mcp_tools -v`. Hai subprocess riêng cho Dev và Tester. Test tạo patch thật, đọc lại file, diff, artifact và xác minh audit cho yêu cầu bị từ chối.

Để kiểm cả Docker, đặt `KTPM_TEST_RUNNER_IMAGE` bằng image ID dựng theo [I15](runner-docker.md) rồi chạy lại cùng lệnh. Tester thêm một test vào `tests_dev/`, gọi `tests.run_suite` trên commit mới và đối chiếu số ca đạt, ID report SQLite và tham chiếu artifact với run.
