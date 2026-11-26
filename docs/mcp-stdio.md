# R07 · Đọc dấu vân tay đề cương qua MCP

Chạy từ thư mục gốc nhánh, với Python 3.11 trở lên.

```sh
python -m pip install mcp==2.3.0
python -m unittest -v tests.test_mcp_stdio
```

Client khởi động server ở một tiến trình riêng, kiểm tra schema từ `tools/list` rồi gọi `project.describe_document`. Đầu vào duy nhất là mã tài liệu `P01`. Test đối chiếu SHA-256 với tệp đề cương tại checkout hiện tại và thử mã ngoài danh mục.

Kết quả ngày 26/11/2026 trên Windows, Python 3.14.7, một test đạt:

```text
mcp=2.3.0 protocol=2026-07-28 tools/list=project.describe_document P01=30776B R99=isError
```

### Đường đi của yêu cầu

```text
MVP: Agent → Host/Gateway kiểm tra quyền → MCP client → stdio → MCP server → tool hoặc runner
R07: Kiểm thử                         → MCP client → stdio → MCP server → đọc đề cương
```

Host quản lý vai trò, quyền và vòng đời của run. Envelope nội bộ mang `run_id`, vai trò và tham chiếu dữ liệu để điều phối sáu agent. SDK chuyển các method như `tools/list` và `tools/call` qua giao thức MCP. Chuỗi `project-doc://approved/P01` trong kết quả do ứng dụng đặt để nhận dạng tài liệu. Server dành stdout cho giao thức và dùng stderr cho log. Runner của MVP chịu trách nhiệm cô lập tiến trình. [Kiến trúc MCP](https://modelcontextprotocol.io/docs/learn/architecture) · [Bảo mật MCP](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)

SDK mô tả tham số tool bằng JSON Schema. Trong phép thử, tool thực hiện thao tác đọc, trả kết quả cấu trúc hoặc báo `isError`. MCP còn hỗ trợ resource để đọc nội dung qua URI và prompt để cung cấp mẫu tương tác. [MCP server concepts](https://modelcontextprotocol.io/docs/learn/server-concepts) · [SDK Python và client](https://py.sdk.modelcontextprotocol.io/client/) · [Hướng dẫn server](https://modelcontextprotocol.io/docs/develop/build-server)
