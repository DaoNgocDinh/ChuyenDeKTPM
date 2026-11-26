# D06 · Kiến trúc và đường đi của một run

Bản đề xuất để duyệt cùng hợp đồng vai trò D05.

```mermaid
flowchart LR
  Owner[Chủ dự án] --> UI[React loopback]
  UI --> API[FastAPI]
  API --> DB[(SQLite metadata)]
  Worker[Worker duy nhất] <-->|lease, checkpoint, events| DB
  Worker --> Host[Host và state machine]
  Host --> Roles[Sáu vai trò và skill đã khóa]
  Roles -->|đề xuất| Host
  Host --> LLM[Adapter model]
  Host -->|lưu artifact bất biến| Art[(Artifact store theo run)]
  Host --> Gate[Gateway kiểm role, run, step]
  Gate --> Client[MCP client]
  Client <-->|stdio| Server[MCP server]
  Server --> WS[Workspace Git của ứng dụng]
  WS --> AppDB[(DB nghiệp vụ của ứng dụng)]
  Server --> Runner[Runner cô lập, không có credential LLM]
  Runner -->|kết quả, commit| Host
  Eval[Harness đánh giá độc lập] -->|đọc mã ở commit| WS
  Eval -->|chạy bộ nghiệm thu riêng| Runner
```

```mermaid
flowchart TD
  O[Orchestrator nhận job] --> R[Requirement làm rõ brief]
  R --> G1{Duyệt requirements}
  G1 -->|yêu cầu sửa| R
  G1 -->|đúng phiên bản| A[Architecture]
  A --> P[Planning tạo DAG]
  P --> G2{Duyệt architecture và plan}
  G2 -->|sửa thiết kế| A
  G2 -->|sửa kế hoạch| P
  G2 -->|đúng cả hai phiên bản| D[Dev ghi patch]
  D --> T[Tester chạy suite ở commit mới]
  T -->|bug mã, còn lượt| D
  T -->|sai yêu cầu| R
  T -->|sai thiết kế| A
  T -->|task đạt| O2[Orchestrator mở task tiếp hoặc nghiệm thu cuối]
  O2 -->|còn task ready| D
  T -->|hết lượt sửa| U[Chủ dự án xem lý do và bằng chứng]
```

### Kiểm tra bằng một fixture

1. Tạo brief A1 và khởi động run. API ghi job rồi trả ID. Worker nhận lease, Orchestrator giao Requirement. Từ chối requirements v1 vì tiêu đề rỗng chưa có tiêu chí. Kiểm tra không có bước Architecture cho tới khi duyệt v2.
2. Architecture xuất hợp đồng API/DB, Planning tạo task cho FR tiêu đề. Duyệt đúng **cả** phiên bản thiết kế và kế hoạch. Đổi một phiên bản trước khi duyệt thì host từ chối.
3. Dev đề xuất patch ở commit gốc qua Gateway/MCP. Tester chạy suite trên commit mới. Với ca mục tiêu đỏ, đính report và trả Dev. Với ca xanh và regression đạt, host mở task kế tiếp.
4. Thử ghi sang `evaluation/` từ bước Dev. Gateway từ chối và ghi sự kiện theo run. Khi vượt quota, host dừng trước tool/model call tiếp. Chủ dự án xem lý do trên timeline. Khi hủy, runner kết thúc cây tiến trình và worker lưu trạng thái.
5. Ngắt worker sau khi phát patch nhưng trước khi xác nhận. Worker mới đối chiếu operation, hash và commit với checkpoint. Nếu kết quả chưa xác định được, chuyển `pending_recovery` để chủ dự án quyết định.

`workspaces/{project_id}/{run_id}/` chứa app, artifact và log của run. SQLite nền tảng chỉ giữ metadata. Evaluation thuộc harness bên ngoài workspace mà agent được ghi. Chỉ adapter được cấp thông tin xác thực model. Runner nhận đúng mã và suite, giới hạn tài nguyên và chính sách mạng.

**Cách test** · Mở hai sơ đồ trong GitHub và lần theo năm bước fixture. Đối chiếu hai lần chờ duyệt, đường lỗi trả về vai trò và vùng được phép ghi với [hợp đồng D05](hop-dong-vai-tro.md).
