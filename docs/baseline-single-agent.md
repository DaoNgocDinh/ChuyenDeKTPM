# E02 · Single-Agent Baseline (`S`) công bằng với cấu hình 6 Agent (`M`)

`backend/baseline_single_agent.py` hiện thực đối chứng **Single-Agent (`S`)** chạy trên **cùng hạ tầng host** với hệ thống 6 agent (`M`) để bảo đảm phép so sánh thực nghiệm công bằng theo mục 5.1–5.2 của kế hoạch nghiên cứu:

- **Một vai trò tổng hợp (`SingleAgentBaseline`)** cắm trực tiếp vào `Worker(queue, baseline)` và thực hiện đủ chuỗi: yêu cầu (`requirements` + Markdown) → **Cổng duyệt 1** → kiến trúc & kế hoạch (`architecture`, `plan`, kiểm `check_handoff`) → **Cổng duyệt 2 nguyên tử** → lặp thực thi/kiểm thử/tự sửa (`dev_result`, `patch`, `test_report`, `ReviewReport` JSON, `bug_report`, giới hạn tối đa 3 vòng sửa mã và ghi `trace_links` `FR → task → patch → test`).
- **Quyền hợp chuyên môn qua MCP `stdio` thật (`SingleAgentGateway` + `baseline_step_client`):** suy ra trực tiếp từ hợp quyền `Dev ∪ Tester` trong `docs/quyen-cong-cu.json` (`write: ["app", "tests_dev"]`, 7 tool MCP và 3 suite runner `build`/`smoke`/`development`), đồng thời **vẫn chặn tuyệt đối** đọc/ghi `evaluation/`, `skills/`, `docs/` và tệp bí mật kèm audit log trong `tool_calls`.
- **Công bằng tài nguyên (`assert_fair_baseline_parity`):** dùng chung model adapter (`backend/llm.py`), `RunSkills` (`I08`), `RunQuotaTracker` (`I19` — một ngân sách duy nhất cho toàn run `S`, không cấp gấp 6 cho `M`), `DockerRunner` (`I15`) và chạy cùng bộ nghiệm thu độc lập `E01` (`evaluation/reporting.py`) tại đúng `code_commit`.

**Test** · `uv run --frozen python -m unittest tests.test_baseline_single_agent tests.test_e01_evaluation tests.test_repair_loop tests.test_tester_agent -v` và `uvx ruff check --select E4,E7,E9,F backend evaluation tests`.
