# BÁO CÁO HOÀN THÀNH CÔNG VIỆC P01

> **Mã công việc**: `P01` ([GitHub Issue #2](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2), thuộc kế hoạch tổng [#1](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/1))  
> **Loại công việc**: Kế hoạch · **Tuần tương đối**: Tuần 1  
> **Nhánh lưu trữ**: `P01` trên kho `DaoNgocDinh/ChuyenDeKTPM`  
> **Ngày lập báo cáo**: 23/11/2026  
> **Trạng thái**: Hoàn thiện báo cáo tổng kết phạm vi `P01` (đã đối chiếu với đề cương duyệt tại commit `8c2fe71`, chờ chủ dự án rà soát cuối trước khi đóng Issue `#2` / cập nhật sổ cái `R10`)  
> **Nguồn chuẩn đối chiếu**: `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (lập ngày 17/11/2026, 30 trang)  
> **SHA256 nguồn chuẩn**: `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`  
> **Mục tham chiếu**: Mục `1.2–1.6`, `2.8`, `3.3–3.6`, `4.3` và `5.1–5.2`  
> **Ranh giới báo cáo**: Tài liệu này tổng kết kết quả thực hiện, quá trình rà soát, bằng chứng và phần còn mở của riêng công việc **`P01`**. Báo cáo này **không** thay thế báo cáo học thuật chính thức 7 phần (`B01`–`B06`) và **không** nghiệm thu trước các hạng mục nghiên cứu (`R01`–`R09`), đặc tả/thiết kế (`D01`–`D11`), hiện thực (`I01`–`I25`), kiểm chứng (`V01`–`V02`) hay thực nghiệm (`E01`–`E08`).

---

## 1. Mục tiêu và phạm vi công việc `P01`

Công việc **`P01` — Chốt phạm vi MVP, câu hỏi nghiên cứu và lộ trình 12 tuần** nhằm đóng băng các đường biên kiểm chứng được cho toàn bộ đề tài *"Nghiên cứu và xây dựng hệ thống Multi-Agent hỗ trợ tự động hóa quy trình phát triển phần mềm — Từ phân tích yêu cầu và thiết kế đến sinh mã, kiểm thử và sửa lỗi"*.

- **Đầu vào gốc**: Không có issue tiền nhiệm; sử dụng trực tiếp bản kế hoạch gốc `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` làm nguồn chuẩn duy nhất khi phát sinh khác biệt với các bản nháp trước đó.
- **Nhiệm vụ trọng tâm**:
  1. Khóa giới hạn công nghệ MVP (`FastAPI`, `React`, `SQLite`, `Git` cục bộ), kiến trúc **1 worker** và **đúng 6 vai trò logic**.
  2. Chốt bộ 3 câu hỏi nghiên cứu **`RQ1`**, **`RQ2`**, **`RQ3`** cùng cách kiểm chứng công bằng và ranh giới giữa giả thuyết với kết luận.
  3. Phân định rõ ranh giới **Trong MVP** và **Ngoài MVP (`F01`–`F05`)**, đầu ra kiểm tra được theo từng tuần và **4 mốc khóa** (Tuần 2, 3, 8, 9).
  4. Xác lập kỷ luật bằng chứng: không coi mã mô phỏng cũ hoặc số liệu dự kiến là kết quả đã đạt.

---

## 2. Tóm tắt kết quả đã chốt trong `P01`

Toàn bộ đặc tả chi tiết đã được lập và duyệt tại [`P01/de_cuong_P01.md`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/8c2fe7180ff08650b1488fe7d169ad9430427b73/P01/de_cuong_P01.md). Phần dưới đây tổng hợp các quyết định đã khóa làm căn cứ triển khai các tuần tiếp theo.

### 2.1. Bản chất hệ thống, giới hạn Stack MVP, 1 Worker và 6 Vai trò

- **Bản chất hệ thống**: Hệ thống multi-agent dựa trên workflow có điều phối tập trung (*workflow-based coordinated MAS*), có kiểm soát của con người tại **2 cổng duyệt xác định** (Cổng 1 sau `Requirement`; Cổng 2 gộp sau `Architecture` + `Planning`).
- **Stack nền tảng và stack ứng dụng đầu ra cố định**:
  - **Backend & Runtime**: `Python >= 3.11`, `FastAPI`, `Pydantic`, state machine điều phối tường minh bằng Python (chạy cục bộ `loopback`, đơn người dùng; không chạy workflow dài trong `FastAPI BackgroundTasks`; không triển khai song song hai runtime với LangGraph).
  - **Frontend**: `React` gồm 4 màn hình gọn dùng **polling** theo cursor (`GET /runs/{id}/events?after=...`), chỉ hoàn thiện sau khi backend chạy xuyên suốt từ đầu đến cuối.
  - **Lưu trữ**: `SQLite` (11 bảng metadata nền tảng, bật `foreign_keys`, transaction ngắn, tách biệt hoàn toàn khỏi DB của ứng dụng được sinh) kết hợp Artifact Store trên đĩa (`workspaces/{project_id}/{run_id}/`) có version bất biến và SHA256.
  - **Quản lý mã**: `Git` cục bộ theo từng run, Host tạo commit checkpoint sau patch hợp lệ có gắn `task_id`, `input_commit`, `expected_hash`; cấm `push`, `force-push`, tự `merge` hoặc xóa lịch sử.
  - **LLM, MCP, Skills & Runner**: 1 LLM Adapter dùng chung model API (ghi usage thật); **1 local MCP server** chạy qua **`stdio`** bằng `MCP Python SDK` cung cấp 5 nhóm công cụ (workspace, patch, git cục bộ, runner test allowlist, đọc artifact); 6 `SKILL.md` ánh xạ cố định 1–1 theo vai trò; runner cô lập không chứa LLM API key và bị hạn chế mạng/tài nguyên; thư mục `evaluation/` tách hoàn toàn khỏi quyền truy cập của `Dev` và `Tester`.
- **Kiến trúc thực thi — 1 Worker duy nhất**:
  - Một run hoạt động tại một thời điểm (`NFR01`); API chỉ ghi job vào hàng đợi bền (trả `202 Accepted` kèm `run_id`, hỗ trợ `idempotency_key`), worker độc lập nhận tuần tự theo `worker_lease`.
  - Hỗ trợ checkpoint (`operation_id`, `patch_hash`, commit trước/sau), `cancel` hủy cây tiến trình con và `pending_recovery` khi thao tác có tác dụng phụ chưa rõ kết quả (`NFR02`, `FR10`).
  - Việc dùng 1 worker giảm tranh chấp ghi trên SQLite và hỗ trợ theo dõi thứ tự sự kiện, nhưng vẫn yêu cầu transaction ngắn, lease, kiểm tra quyền theo run và lưu đủ cấu hình/phiên bản/log (không tự bảo đảm kết quả LLM lặp lại hoàn toàn).
- **Tổ chức đúng 6 vai trò logic**:
  1. `Orchestrator` (`workflow-coordination`) — điều phối trạng thái, giao task, phân loại lỗi, quản lý quota; không tự duyệt thay người dùng và không sửa mã.
  2. `Requirement` (`requirements-analysis`) — tạo `requirements.json` + bản Markdown duyệt; không sửa bản đã duyệt và không tự thêm tính năng ngoài phạm vi.
  3. `Architecture` (`architecture-design`) — tạo `architecture.md`, ADR, DB schema, OpenAPI, bố cục FE, chiến lược test trong stack đã khóa.
  4. `Planning` (`task-planning`) — tạo `tasks.json` dạng DAG không chu trình bao phủ toàn bộ FR; không trộn lập kế hoạch với viết mã.
  5. `Dev` (`implementation`) — chỉ ghi mã trong vùng `app` của workspace đúng run; không tự nghiệm thu cuối và không chạm `evaluation/`, `skills/`, prompt, policy hay mã nền tảng.
  6. `Tester` (`testing-review`) — review mã và viết/chạy test phát triển trong `tests_dev` qua runner thật, xuất `review_report.json` và `bug_report.json`; không sửa mã `app` và không tách thêm `Reviewer Agent`.
  - **Vòng phản hồi `Tester → Dev`**: Giới hạn cứng **tối đa 3 vòng sửa** sau lần triển khai đầu của mỗi task (và tuân thủ trần ngân sách tổng toàn run); lỗi thuộc yêu cầu hoặc thiết kế phải định tuyến quay về đúng `Requirement` hoặc `Architecture` để tăng phiên bản và duyệt lại.
  - **Bộ bài toán chuẩn đã khóa (theo bản Word gốc)**: **A1** Quản lý công việc, **A2** Ghi chú có nhãn, **A3** Kho hàng nhỏ — mỗi bài là ứng dụng web CRUD nhỏ (2–3 bảng) trên stack cố định `FastAPI + React + SQLite` với đúng **10 tiêu chí chấp nhận độc lập**.

### 2.2. Câu hỏi nghiên cứu `RQ1–RQ3` và ranh giới Giả thuyết — Kết luận

| Mã | Câu hỏi nghiên cứu đã chốt | Giả thuyết / định hướng đánh giá ban đầu | Phương pháp kiểm chứng bắt buộc | Trạng thái kết luận tại `P01` |
|---|---|---|---|---|
| **RQ1** | Hệ thống **6 agent (`M`)** có cải thiện mức đáp ứng yêu cầu so với **1 agent (`S`)** khi dùng cùng model, bộ công cụ và trần ngân sách tổng không? | Giả thuyết: phân vai và kiểm tra chéo (`Tester → Dev`) có thể cải thiện mức đáp ứng yêu cầu. Do MVP chạy tuần tự trong **1 worker**, **không** viện dẫn xử lý đồng thời làm lợi thế. | **18 run chính** (`3 bài × 3 lặp × 2 cấu hình S/M`), chia chung cùng một trần ngân sách tổng (không nhân sáu), chấm bằng bộ test nghiệm thu độc lập (10 tiêu chí/bài), đo thêm build/smoke, thời gian, token và chi phí. | **Mở — chờ thực nghiệm** (chấp nhận cả khả năng `M` kém hơn `S`). |
| **RQ2** | **Agent Skill** ảnh hưởng như thế nào đến độ đầy đủ của artifact và tỷ lệ lỗi bàn giao? | Giả thuyết: đóng gói quy trình và chuẩn đầu ra trong `SKILL.md` có thể tăng độ đầy đủ artifact và giảm lỗi bàn giao. | Chấm rubric artifact (`0/1/2`), thống kê lỗi schema/bàn giao, và chạy thăm dò **3 run `M` không nạp skill trên `A3`** (theo điều kiện ngân sách trong protocol) đối chiếu với 3 run `M` có skill của `A3`. | **Mở — chờ thực nghiệm** (chấp nhận cả khả năng skill chưa tạo khác biệt rõ). |
| **RQ3** | Tích hợp **MCP** có đáp ứng được giao diện công cụ chuẩn hóa, kiểm soát quyền và khả năng truy vết cần thiết không? | Đánh giá kiến trúc tích hợp 1 local MCP server (`stdio`, 5 nhóm tool) kết hợp `Host/Tool Gateway`, `Runner` cô lập và `SQLite` trên 3 tiêu chí định lượng: (1) discovery & schema dùng chung cho `S`/`M`, (2) hiệu lực chặn sai quyền/path traversal/shell tùy ý tại tầng thực thi, (3) chuỗi log `tool_calls`/`trace_links` kèm đánh đổi độ trễ. | Bộ **MCP contract tests** (`V02`: discovery/call, schema, input sai, timeout, sai quyền/role, path traversal/symlink, độ trễ) và log gọi MCP thật qua SDK chính thức; không suy diễn MCP tự động làm tăng chất lượng mã. | **Mở — chờ kiểm chứng kỹ thuật & log thật** (chấp nhận cả đánh đổi tăng độ trễ). |

### 2.3. Ranh giới Trong MVP vs Ngoài MVP (`F01`–`F05`)

- **Giữ cứng trong MVP**: 6 vai trò logic dùng chung 1 model API; 3 bài CRUD nhỏ (`A1`, `A2`, `A3`) trên stack cố định; 1 worker + SQLite + local MCP (`stdio`) + Git cục bộ; 2 cổng duyệt + tối đa 3 vòng sửa/task + `cancel`/`resume`/`pending_recovery` cơ bản; 3 pilot + 18 run chính (`S`/`M`) + 3 run thăm dò `M` bỏ skill trên `A3` + MCP contract tests.
- **Hoãn sang sau MVP (`F01`–`F05`, không phải điều kiện đóng kế hoạch tổng `#1`)**:
  - `F01`: Mở rộng bộ bài toán, số lần lặp, kiểm tra UI nâng cao hoặc chạy bỏ skill đủ cả 3 bài.
  - `F02`: Quản lý thay đổi yêu cầu, truy vết tác động và cơ chế resume/compensation nâng cao.
  - `F03`: Chuyển sang PostgreSQL và cơ chế job bền nhiều worker.
  - `F04`: Remote MCP, OAuth/xác thực, tự tạo issue/PR, `push`/`merge` remote và CI/CD.
  - `F05`: Chọn skill động theo nhiệm vụ hoặc dùng nhiều model khác nhau theo vai trò.

### 2.4. Lộ trình 12 tuần tương đối, 4 mốc khóa và thứ tự ưu tiên

- **Khung thời gian lập kế hoạch**: 12 tuần tương đối với giả định quỹ thời gian **12–16 giờ/tuần** theo tài liệu gốc (chưa gán ngày bắt đầu thực tế, hạn bảo vệ thực tế hay cam kết thời gian cá nhân).
- **4 mốc khóa bắt buộc**:
  1. **Tuần 2 — Khóa phạm vi nghiệp vụ**: Chốt `D01`–`D04` (FR01–FR10, NFR01–NFR08 và 3 bài thử `A1`, `A2`, `A3`).
  2. **Tuần 3 — Khóa hợp đồng kỹ thuật**: Chốt `D05`–`D11` (contract 6 agent, schema artifact, state machine, ERD, API, ma trận quyền & runner profile).
  3. **Cuối Tuần 8 — Đóng tính năng mới**: Hoàn tất `V01`; dừng thêm tính năng nền tảng mới.
  4. **Tuần 9 — Khóa cấu hình thực nghiệm**: Hoàn tất `E04` sau 3 run pilot; đóng băng protocol, model/tham số, prompt/skill, brief/fixture, bộ test độc lập, runner image và system commit trước khi chạy 18 run chính ở Tuần 10.
- **Ràng buộc phụ thuộc đã lưu ý**: Bản lõi chạy thật của `I13` (Tool Gateway) và `I14` (MCP `stdio`) phải hoàn thành trong Tuần 6 để mở `I15` và `I16`; lượt contract test chính của `V02` phải hoàn thành trước mốc freeze Tuần 9 để mở `E04`.
- **Thứ tự ưu tiên khi chậm tiến độ**: (1) Giữ cứng 6 agent, artifact phiên bản, vòng `Dev–Tester`, MCP tools, bộ test độc lập và trọn 18 run chính; (2) Tinh gọn giao diện (giữ polling, 1 stack, 1 worker, SQLite); (3) Hoãn toàn bộ `F01`–`F05`; không bao giờ giảm số lần lặp sau khi thấy kết quả bất lợi.

---

## 3. Đối chiếu tiêu chí hoàn thành & Quá trình rà soát điều chỉnh

### 3.1. Bảng đối chiếu với Issue `#2 [P01]`

| Hạng mục trong Issue `#2` | Kết quả thực hiện | Bằng chứng đối chiếu |
|---|---|---|
| Lập đề cương, giới hạn stack `FastAPI/React/SQLite/Git`, 1 worker và đúng 6 vai trò logic | Đạt | Mục `3`, `4`, `5` của [`P01/de_cuong_P01.md`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/8c2fe7180ff08650b1488fe7d169ad9430427b73/P01/de_cuong_P01.md) |
| Chốt `RQ1` so sánh `S/M`; `RQ2` ảnh hưởng skill; `RQ3` tích hợp MCP theo bản Word cuối | Đạt | Mục `2` của `P01/de_cuong_P01.md` và quyết định giữ `RQ1–RQ3` ở trạng thái chờ kiểm chứng |
| Định nghĩa mốc Tuần 2 khóa phạm vi, Tuần 3 khóa hợp đồng, Tuần 8 đóng tính năng, Tuần 9 khóa thực nghiệm | Đạt | Mục `8.1`, `8.2` của `P01/de_cuong_P01.md` |
| Đề cương được người thực hiện duyệt; chỉ rõ trong/ngoài MVP và đầu ra từng tuần | Đạt | Mục `6`, `8.1`, `10` của `P01/de_cuong_P01.md` và bình luận duyệt [`#issuecomment-7099047910`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7099047910) |
| Không coi code mô phỏng cũ hoặc số liệu dự kiến là kết quả đã đạt | Đạt | Mục `2`, `9`, `10` của `P01/de_cuong_P01.md` |

### 3.2. Các điểm đã hiệu chỉnh qua quá trình rà soát

Trong quá trình rà soát và duyệt đề cương ngày 23/11/2026 (đối chiếu giữa bình luận [`#issuecomment-7098944431`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7098944431), kết quả duyệt [`#issuecomment-7099047910`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7099047910), đề cương commit `8c2fe71` và bình luận cập nhật [`#issuecomment-7102034018`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7102034018)), các điểm sau đã được chuẩn hóa:

1. **Tách bạch giả thuyết với kết luận thực nghiệm**: Nhận định ban đầu ở `#issuecomment-7098944431` rằng 6 agent dễ cải thiện hơn 1 agent và skill tăng đầu ra được chuẩn hóa lại thành **giả thuyết cần kiểm chứng** tại Mục `2` của `P01/de_cuong_P01.md`. Ở `#issuecomment-7102034018`, chủ dự án đã sửa diễn đạt `RQ1` thành giả thuyết và bổ sung khung đánh giá định lượng cho `RQ3`; riêng diễn đạt `RQ2` trong bình luận đó vẫn có sắc thái khẳng định, nên báo cáo này ghi nhận thống nhất theo đề cương đã duyệt rằng **`RQ2` vẫn là giả thuyết chờ kiểm chứng bằng rubric và 3 run thăm dò bỏ skill trên `A3`**.
2. **Loại bỏ lập luận xử lý đồng thời ở `RQ1`**: Do MVP chạy 1 worker tuần tự, mọi ưu thế tiềm năng của cấu hình `M` (nếu có) chỉ được kiểm chứng trên khía cạnh phân vai chuyên môn hóa và kiểm tra chéo trong cùng trần ngân sách tổng.
3. **Chuẩn hóa sơ đồ kiến trúc 6 vai trò**: Sơ đồ trong `P01/de_cuong_P01.md` đã bổ sung đủ đường nạp ngữ cảnh/LLM và quyền Tool Gateway cho cả 6 vai trò (bao gồm `Orchestrator`), đồng thời thể hiện rõ thành phần `MCP Client` nằm trong Host trước `Local MCP Server (stdio)`.
4. **Hiệu chỉnh lập luận về 1 worker**: Loại bỏ khẳng định tuyệt đối rằng chỉ riêng 1 worker là tự đảm bảo chống tranh chấp tuyệt đối hay tái lập 100% kết quả LLM; bổ sung yêu cầu transaction ngắn, `worker_lease`, kiểm tra quyền theo run và lưu đầy đủ cấu hình/phiên bản/log.
5. **Trung thực với thông tin chưa chốt**: Giữ lịch 12 tuần tương đối, ghi rõ `12–16 giờ/tuần` là giả định lập kế hoạch, chưa gán ngày bắt đầu/hạn bảo vệ thực tế và chưa tự điền chuẩn trích dẫn/quy định AI của trường.

---

## 4. Danh mục bằng chứng và liên kết truy vết

| Hạng mục | Định danh / Đường dẫn | Ghi chú xác minh |
|---|---|---|
| Nguồn chuẩn gốc | `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (17/11/2026) | Đã kiểm tra khớp SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F` |
| Kế hoạch tổng | [Issue #1](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/1) | Backlog 65 công việc chính + 5 hạng mục sau MVP (`F01`–`F05`) |
| Issue công việc `P01` | [Issue #2](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2) | Checklist 5/5 mục đã đánh dấu hoàn thành; trạng thái issue tại thời điểm lập báo cáo: `OPEN` |
| Đề cương đã duyệt | [`P01/de_cuong_P01.md` tại commit `8c2fe71`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/8c2fe7180ff08650b1488fe7d169ad9430427b73/P01/de_cuong_P01.md) | Commit phê duyệt `8c2fe7180ff08650b1488fe7d169ad9430427b73` trên `main` (và là commit nền của nhánh `P01`, `R10`) |
| Bình luận đề cương & trả lời sơ bộ | [`#issuecomment-7098944431`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7098944431) | Ghi nhận đề cương demo và trao đổi ban đầu cho `RQ1`–`RQ3` (`2026-11-23T11:02:50Z`) |
| Bình luận kết quả duyệt `P01` | [`#issuecomment-7099047910`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7099047910) | Xác nhận kết quả duyệt `P01` — đạt kèm các điểm hiệu chỉnh (`2026-11-23T11:06:20Z`) |
| Bình luận cập nhật `RQ1`–`RQ3` | [`#issuecomment-7102034018`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7102034018) | Chủ dự án làm rõ giả thuyết `RQ1` và khung đánh giá `RQ3` (`2026-11-23T13:05:06Z`) |
| Ghi nhận trong sổ cái `R10` | [`R10/so_cai_hoan_thanh.md` tại commit `93b6362`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/93b6362ed94badf2a0e6ee109b32a74161155cca/R10/so_cai_hoan_thanh.md) | Trên nhánh `R10` ([Issue #12](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/12)); đã ghi nhận `P01` hoàn thành theo xác nhận của chủ dự án |
| Khởi tạo tệp báo cáo `P01` | Commit `2acc5d0` trên nhánh `P01` (`2acc5d014d9dae1ba60137b893468b2f15003e10`) | Khởi tạo `P01/bao_cao_P01.md` ở trạng thái chờ viết; nội dung hoàn thiện được cập nhật ngay trên nhánh `P01` |

---

## 5. Phần còn mở, giới hạn và công việc kế tiếp

### 5.1. Phần còn theo dõi và giới hạn hiện trạng
- **Trạng thái quản trị trên GitHub**: Issue `#2` hiện vẫn đang ở trạng thái `OPEN`; nhánh `P01` chưa merge về `main`. Việc đóng Issue `#2`, merge nhánh `P01` và cập nhật lại ghi chú về `P01/bao_cao_P01.md` trong sổ cái `R10/so_cai_hoan_thanh.md` (trên nhánh `R10`) sẽ thực hiện theo quyết định của chủ dự án sau khi rà soát báo cáo này.
- **Thông tin hành chính/học thuật chưa có dữ liệu**: Ngày bắt đầu Tuần 1 thực tế, hạn bảo vệ thực tế, chuẩn trích dẫn chính thức và quy định sử dụng AI của trường vẫn chưa có thông tin xác nhận và tiếp tục được theo dõi tại `R10` ([Issue #12](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/12)).
- **Giới hạn phạm vi**: `P01` chỉ chốt đề cương và ranh giới MVP; chi tiết hợp đồng 6 agent, JSON/Pydantic schema, state machine, ERD SQLite, OpenAPI, ma trận quyền MCP và runner profile chưa được chốt ở bước này mà thuộc phạm vi `D05`–`D11` (Tuần 3).

### 5.2. Công việc tiếp theo ngay sau `P01`
- **Phần còn lại của Tuần 1**:
  - [`R01` (#3)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3): Học AI Agent, MAS, SDLC và thống nhất thuật ngữ.
  - [`R02` (#4)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/4): Nghiên cứu ReAct và phân biệt workflow với agent.
  - [`R10` (#12)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/12): Tiếp tục duy trì sổ cái hoàn thành, phiếu nguồn và nhật ký AI; cập nhật trạng thái báo cáo `P01` sau khi rà soát.
  - [`B01` (#59)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/59): Mở khung Phần 1 (chỉ nghiệm thu sau khi đủ nguồn đã đọc ở `R01`–`R10`).
- **Tuần 2 (hướng tới Mốc khóa 1 — Khóa phạm vi nghiệp vụ)**:
  - Đọc 4 nghiên cứu liên quan `R03`–`R06` (`#5`–`#8`): MetaGPT, ChatDev, SWE-agent, SWE-bench.
  - Đặc tả `D01`–`D04` (`#13`–`#16`): FR01–FR10, NFR01–NFR08 và 10 tiêu chí chấp nhận cho từng bài `A1`, `A2`, `A3`; khởi động `E01` (`#51`).

---

## 6. Kỷ luật bằng chứng & Nhật ký hỗ trợ AI

- **Đầu vào sử dụng**: `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`), `P01/de_cuong_P01.md` (commit `8c2fe71`), `R10/so_cai_hoan_thanh.md` (commit `93b6362`), và dữ liệu công khai trên kho `DaoNgocDinh/ChuyenDeKTPM` (Issues `#1`, `#2` kèm 3 bình luận, `#12`, `#59`, nhánh `main`, `P01`, `R10`).
- **Phạm vi hỗ trợ AI**: Tổng hợp nội dung báo cáo hoàn thành `P01` vào `P01/bao_cao_P01.md` và cập nhật lên nhánh `P01` theo yêu cầu trực tiếp của chủ dự án.
- **Kiểm chứng đã thực hiện**: Đối chiếu toàn bộ mã issue, commit SHA, URL bình luận, tên 3 bài toán (`A1`, `A2`, `A3`), 4 mốc khóa, SHA256 tài liệu chuẩn và đọc lại tệp cục bộ lẫn phiên bản trên nhánh `P01` sau khi cập nhật.
- **Giới hạn trách nhiệm**: Báo cáo không chứa số liệu thực nghiệm hay kết luận nghiên cứu đi trước bằng chứng. Chủ dự án cần trực tiếp rà soát và xác nhận nội dung báo cáo trước khi đóng Issue `#2` hoặc merge nhánh `P01`.
