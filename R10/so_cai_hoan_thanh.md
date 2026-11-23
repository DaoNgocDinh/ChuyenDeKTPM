# R10 — SỔ CÁI CÔNG VIỆC ĐÃ HOÀN THÀNH

> Thuộc [R10 — issue #12](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/12), kế hoạch tổng #1.  
> Khởi tạo ngày 23/11/2026. R10 đang thực hiện, tiếp tục cập nhật trong suốt đề tài.

Mỗi công việc hoàn thành được ghi kèm ngày, kết quả, căn cứ xác nhận và bằng chứng có thể truy lại. Khi điều chỉnh một mục đã ghi, bổ sung lịch sử thay đổi và lý do.

## Danh sách hoàn thành

| Mã | Công việc | Ngày ghi nhận hoàn thành | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| P01 | Chốt phạm vi MVP, câu hỏi nghiên cứu và lộ trình 12 tuần | 23/11/2026 | Đã hoàn thành theo xác nhận của chủ dự án | [Đề cương đã duyệt tại commit 8c2fe71](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/8c2fe7180ff08650b1488fe7d169ad9430427b73/P01/de_cuong_P01.md), [kết quả duyệt](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7099047910) |

## Theo dõi công việc chờ rà soát nghiệm thu

*(Các công việc ở bảng dưới đã có sản phẩm/báo cáo nháp hoặc hoàn thiện trên nhánh riêng nhưng **chưa** có quyết định nghiệm thu của chủ dự án; chưa được tính vào `Danh sách hoàn thành`.)*

| Mã | Công việc | Ngày cập nhật | Trạng thái thực tế | Bằng chứng hiện có |
|---|---|---|---|---|
| R01 | Học AI Agent, MAS, SDLC và thống nhất thuật ngữ | 23/11/2026 | Đã hoàn thiện báo cáo trên nhánh `R01` — **chờ chủ dự án rà soát và quyết định nghiệm thu** | [Báo cáo R01 tại commit 32b2ce7](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/32b2ce78a1ab602259899d77d0943c624fd226d2/R01/bao_cao_R01.md), [commit `32b2ce7`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/commit/32b2ce78a1ab602259899d77d0943c624fd226d2), [bản tổng hợp bàn giao](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3#issuecomment-7104514172) |

## Bản ghi P01 — 23/11/2026

- **Công việc:** [P01 — issue #2](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2).
- **Căn cứ ghi nhận:** Chủ dự án xác nhận trong chat rằng P01 đã xong và yêu cầu cập nhật sổ cái; đề cương và bình luận duyệt P01 đã có trên GitHub.
- **Đầu ra hoàn thành:** `P01/de_cuong_P01.md`, phiên bản tại commit `8c2fe7180ff08650b1488fe7d169ad9430427b73`.
- **Nguồn chuẩn được đề cương tham chiếu:** `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx`, lập ngày 17/11/2026; SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`.

### Kết quả đã chốt

- Phạm vi MVP: FastAPI, React, SQLite, Git cục bộ; một worker và đúng sáu vai trò logic.
- RQ1 so sánh single-agent/multi-agent, RQ2 đánh giá ảnh hưởng skill, RQ3 đánh giá tích hợp MCP.
- Ranh giới trong/ngoài MVP, đầu ra từng tuần và lộ trình 12 tuần tương đối.
- Bốn mốc khóa: tuần 2 khóa phạm vi, tuần 3 khóa hợp đồng, tuần 8 đóng tính năng mới, tuần 9 khóa thực nghiệm.
- Nguyên tắc bằng chứng: RQ1–RQ3 còn chờ kiểm chứng; chưa có kết luận thực nghiệm từ việc hoàn thành P01.

### Kiểm tra và phần còn theo dõi

- Đã kiểm tra đề cương hiện có, checklist của issue #2 và bình luận duyệt có liên kết tới commit bằng chứng.
- Tại thời điểm lập bản ghi, issue #2 trên GitHub đang mở; trạng thái hoàn thành trong sổ cái được ghi theo xác nhận của chủ dự án, không đồng nghĩa issue đã được đóng.
- File `P01/bao_cao_P01.md` được khởi tạo trên nhánh `P01`, đang chờ viết theo yêu cầu; chưa được tính là báo cáo đã hoàn thành.
- Chuẩn trích dẫn và quy định sử dụng AI của trường tiếp tục cần xác minh trong R10.
- R10 tiếp tục quản lý phiếu nguồn, nhật ký tự học và việc dùng AI theo issue #12.

### Nhật ký hỗ trợ AI trong lần cập nhật này

- **Đầu vào:** Yêu cầu của chủ dự án, đề cương P01 hiện có, issue #2, bình luận duyệt và mô tả R10 tại issue #12.
- **Phạm vi hỗ trợ:** Tạo nhánh P01 và R10; tạo file chờ viết báo cáo P01; khởi tạo sổ cái và ghi nhận P01 hoàn thành.
- **Kiểm chứng:** Đối chiếu thông tin với các tài liệu và bằng chứng nêu trên; đọc lại file sau khi lưu.
- **Giới hạn:** Bản ghi này không xác nhận người thực hiện đã đọc các nguồn học thuật hoặc đã hoàn thành nghiên cứu, thiết kế, triển khai và thực nghiệm tiếp theo.

## Theo dõi R01 — 23/11/2026 (chưa nghiệm thu)

- **Công việc:** [R01 — issue #3](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3) (tiền nhiệm: [P01 — issue #2](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2)).
- **Căn cứ cập nhật:** Chủ dự án yêu cầu tạo nhánh riêng `R01`, viết báo cáo `R01` trên nhánh `R01` và cập nhật tại `R10`, dựa trên [bản tổng hợp bàn giao tại issue #3](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3#issuecomment-7104514172) và [phiếu bàn giao tại issue #12](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/12#issuecomment-7104515223).
- **Đầu ra hiện có:** `R01/bao_cao_R01.md` trên nhánh `R01` (khởi tạo từ `main` commit `8c2fe7180ff08650b1488fe7d169ad9430427b73`), phiên bản tại commit [`32b2ce78a1ab602259899d77d0943c624fd226d2`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/commit/32b2ce78a1ab602259899d77d0943c624fd226d2).
- **Nguồn chuẩn đối chiếu:** `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx`, lập ngày 17/11/2026; SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`.
- **Dấu vết bình luận gốc được bảo lưu:** `#issuecomment-7102831272`, `#issuecomment-7103979295`, `#issuecomment-7104352917`, `#issuecomment-7104514172` trên issue `#3`.

### Nội dung chính đã lập trong `R01/bao_cao_R01.md`

- Nền tảng LLM, AI Agent (4 đặc tính *weak notion* của Wooldridge–Jennings, phân biệt Agent vs lời gọi LLM đơn lẻ, ranh giới Model vs Host/Runtime), MAS và định vị *workflow-based coordinated MAS* (tách rõ lý thuyết nguồn gốc khỏi quyết định thiết kế của kế hoạch).
- Bảng 7 pha SDLC (đầu vào, đầu ra cần kiểm tra, rủi ro lan truyền), 4 mô hình SDLC, phạm vi MVP và phân biệt lập kế hoạch dự án đầu SDLC với `Planning Agent` đứng sau `Architecture`.
- Bảng 18 thuật ngữ thống nhất và ranh giới thành phần (không tính Agent hỗ trợ, Worker, State Machine, MCP server, Runner, Skill là agent thứ 7; chuẩn hóa tên `Tester Agent`).
- Mô hình đúng 6 vai trò logic kèm sơ đồ phối hợp Mermaid chuẩn hóa, đầy đủ 12 nhóm luồng hoạt động dự kiến trong MVP và ví dụ minh họa giả định trên `A1` (`FR-T01 → TASK-03 → P1/C1 → BUG-01 → P2/C2 → retest`).
- Phiếu nguồn cho 5 nhóm tài liệu (`Wooldridge & Jennings 1995`, `AWS LLM & SDLC`, `Anthropic 19/12/2024`, `Gimasys`, `Kế hoạch dự án 17/11/2026`) và bảng đối chiếu từng tiêu chí của issue `#3`.

### Kiểm tra, phần còn chưa chắc và điều kiện nghiệm thu

- **Trạng thái nghiệm thu:** `R01` **chưa** được đưa vào `Danh sách hoàn thành` và issue `#3` vẫn giữ `OPEN`. Chủ dự án cần trực tiếp rà soát `R01/bao_cao_R01.md`, xác nhận phạm vi/ngày tự đọc các nguồn rồi quyết định nghiệm thu; sau đó mới cập nhật `R01` sang mục đã hoàn thành.
- **Kỷ luật nguồn đọc:** Ngày `23/11/2026` là ngày trợ lý bàn giao và Anti đã đối chiếu trực tiếp các nguồn Wooldridge–Jennings, AWS và Anthropic; không tự ghi thay ngày tự đọc của người thực hiện. Nguồn `Gimasys` giữ làm nguồn nhập môn do người thực hiện cung cấp, chưa xác minh toàn bộ.
- **Điểm còn chưa chắc / để mở cho các issue sau:**
  - Cơ chế ReAct và phân tích sâu Workflow vs Agent: chuyển sang `R02` (`#4`).
  - Nghiên cứu liên quan MetaGPT, ChatDev, SWE-agent, SWE-bench: `R03`–`R06` (`#5`–`#8`).
  - Chi tiết kỹ thuật MCP và Agent Skills: `R07`–`R09`.
  - Hợp đồng JSON/Pydantic, ánh xạ chính thức `needs_clarification` / bảng chuyển trạng thái, ERD SQLite, OpenAPI, ma trận quyền và runner profile: `D05`–`D11`.
  - Câu hỏi nghiên cứu `RQ1`–`RQ3`: giữ mở chờ kiểm chứng thực nghiệm; mọi ví dụ pass/fail trong báo cáo `R01` chỉ mang tính minh họa.
  - Chuẩn trích dẫn và quy định AI của trường: tiếp tục xác minh trong `R10`.

### Nhật ký hỗ trợ AI trong lần cập nhật `R01`

- **Đầu vào:** Yêu cầu của chủ dự án, `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (đã xác minh SHA256 cục bộ), `P01/de_cuong_P01.md` (commit `8c2fe71`), issue `#3` (4 bình luận), issue `#12` (`#issuecomment-7104515223`) và đối chiếu web các nguồn Wooldridge–Jennings, AWS, Anthropic.
- **Phạm vi hỗ trợ:** Anti tạo nhánh `R01` từ `main` (`8c2fe71`), viết và commit `R01/bao_cao_R01.md` tại `32b2ce7`, cập nhật sổ cái `R10/so_cai_hoan_thanh.md` trên nhánh `R10` và đăng bình luận đối chiếu tiêu chí `R01` tại issue `#12`.
- **Kiểm chứng:** Xác minh SHA256 tài liệu chuẩn, đọc lại `R01/bao_cao_R01.md` và `R10/so_cai_hoan_thanh.md` sau khi lưu/commit; giữ đúng ranh giới không tự đánh dấu hoàn thành `R01` hay `R10`.
- **Giới hạn:** Bản cập nhật không xác nhận chủ dự án đã tự đọc hết mọi nguồn, không xác nhận `R01` đã được nghiệm thu và không phản ánh kết quả chạy thật hay thực nghiệm.

## Lịch sử cập nhật

| Ngày | Nội dung | Căn cứ |
|---|---|---|
| 23/11/2026 | Khởi tạo sổ cái R10 và ghi nhận P01 hoàn thành; tạo file báo cáo P01 ở trạng thái chờ viết | Yêu cầu của chủ dự án và bằng chứng P01 được liên kết ở trên |
| 23/11/2026 | Bổ sung mục theo dõi chờ nghiệm thu cho R01 kèm link báo cáo `R01/bao_cao_R01.md` tại commit `32b2ce7` trên nhánh `R01` (chưa ghi hoàn thành, chờ chủ dự án rà soát) | Yêu cầu của chủ dự án, bản bàn giao `#issuecomment-7104514172`, phiếu bàn giao `#issuecomment-7104515223` và commit `32b2ce7` |
