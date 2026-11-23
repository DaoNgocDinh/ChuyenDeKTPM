# BÁO CÁO NGHIÊN CỨU NGẮN CÔNG VIỆC R02

> **Mã công việc**: `R02` ([GitHub Issue #4](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/4), thuộc kế hoạch tổng [#1](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/1); tiền nhiệm: [`R01` (#3)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3))  
> **Loại công việc**: Tìm hiểu · **Tuần tương đối**: Tuần 1  
> **Nhánh lưu trữ**: `R02` trên kho `DaoNgocDinh/ChuyenDeKTPM` (khởi tạo từ nền `main` commit `8c2fe71`)  
> **Ngày lập báo cáo**: 24/11/2026  
> **Trạng thái**: Đã lập bản báo cáo nhỏ `R02` trên nhánh riêng `R02` — **chờ chủ dự án rà soát và quyết định nghiệm thu** (chưa đóng Issue `#4`, chưa chuyển vào danh sách đã hoàn thành của sổ cái `R10`)  
> **Nguồn chuẩn đối chiếu**: `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (17/11/2026; SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`), mục `2.1` và `2.3`  
> **Đầu vào ghi chú của chủ dự án**: [Bình luận `#issuecomment-7109633981` (`2026-11-23T18:05:21Z`, tức `01:05` ngày `24/11/2026` GMT+7)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/4#issuecomment-7109633981)  
> **Ranh giới báo cáo**: Đây là bản báo cáo ngắn phục vụ nghiệm thu riêng công việc **`R02`**, tách bạch rõ: (a) ý từ ghi chú của chủ dự án, (b) kiến thức đối chiếu từ 2 nguồn gốc (`ReAct v3`, `Anthropic 19/12/2024`), (c) quyết định thiết kế của kế hoạch đề tài, và (d) ví dụ minh họa giả định. Tài liệu **không** chứa kết quả chạy thật hay kết luận thực nghiệm (`RQ1`–`RQ3` giữ mở).

---

## 1. Mục tiêu và nguồn đầu vào của `R02`

- **Mục tiêu (Issue `#4`)**: Chọn cơ chế hành động có phản hồi và giới hạn rõ cho nguyên mẫu 6 vai trò.
- **Tình trạng tiền nhiệm (`R01` — `#3`)**: Đã có báo cáo [`R01/bao_cao_R01.md`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/32b2ce78a1ab602259899d77d0943c624fd226d2/R01/bao_cao_R01.md) tại commit `32b2ce7` trên nhánh `R01`; Issue `#3` đã được đóng trên GitHub nhưng trong sổ cái `R10` vẫn chờ xác nhận nghiệm thu chính thức của chủ dự án.
- **Nội dung chủ dự án đã ghi nhận tại `#issuecomment-7109633981`**:
  - Phân biệt **Workflow** (điều phối LLM và công cụ theo đường dẫn mã có trước) với **Agent** (LLM tự động điều khiển quy trình và việc dùng công cụ).
  - Rút ra 3 mẫu workflow trọng tâm từ Anthropic: **Prompt chaining** (có cổng kiểm tra trung gian), **Orchestrator-workers**, **Evaluator-optimizer**.
  - Trình bày lý do kết hợp suy luận + hành động + phản hồi trong **ReAct** (điểm mù của `CoT` đơn lẻ, `Act` đơn lẻ; cộng hưởng 2 chiều `Reason to Act` & `Act to Reason`) và định nghĩa ngắn `Thought`, `Action`, `Observation` *(chủ dự án ghi chú trung thực rằng phần trình bày chi tiết `Thought/Action/Observation` còn khó diễn đạt bằng lời riêng)*.

---

## 2. Tổng hợp nghiên cứu từ hai nguồn gốc và giới hạn của từng nguồn

### 2.1. ReAct: Vòng hành động–quan sát và giới hạn nguồn (`arXiv:2210.03629v3`)

- **Cơ chế cốt lõi** ([Yao et al., 10/03/2023 — ICLR 2023](https://arxiv.org/html/2210.03629v3)): Mở rộng không gian hành động từ $\mathcal{A}$ thành $\hat{\mathcal{A}} = \mathcal{A} \cup \mathcal{L}$, xen kẽ **suy luận bằng ngôn ngữ (`Thought`)** với **hành động tương tác môi trường (`Action`)** và **phản hồi thực tế (`Observation`)**:
  - **`Thought`**: Không tác động ra môi trường ngoài; đóng vai trò *bộ nhớ làm việc* để phân rã mục tiêu, trích xuất dữ kiện từ quan sát, theo dõi tiến độ, xử lý ngoại lệ/sửa truy vấn và tổng hợp kết quả.
  - **`Action`**: Lệnh gửi tới công cụ/môi trường ngoài (ví dụ `search`, `lookup`, `finish` trên Wikipedia; `go to`, `take`, `clean` trong ALFWorld).
  - **`Observation`**: Phản hồi khách quan môi trường trả về, giúp neo suy luận vào sự thật (*grounding*) thay vì suy đoán khép kín như `CoT`.
- **Cộng hưởng hai chiều**: `Reason to Act` (suy luận để lập kế hoạch, chia nhỏ mục tiêu, xoay xở ngoại lệ) và `Act to Reason` (hành động lấy dữ liệu thật làm căn cứ suy luận).
- **Giới hạn đã được chính bài báo chỉ ra (Mục 3.3, Bảng 2 trên 200 mẫu HotpotQA & Mục 6)**:
  1. **Giảm ảo giác nhưng tăng lỗi suy luận và lặp bước**: Trong 50 ca thất bại khảo sát, ReAct giảm ảo giác từ `56%` (CoT) xuống **`0%`**, nhưng tỷ lệ **lỗi suy luận tăng lên `47%`** (so với `16%` của CoT), nổi bật là mẫu lỗi **lặp lại chính `Thought` và `Action` trước đó** không tự thoát được (tác giả gợi ý một phần do *greedy decoding* và đặt trần 7 bước ở HotpotQA / 5 bước ở FEVER rồi lùi về `CoT-SC`).
  2. **Phụ thuộc mạnh vào chất lượng công cụ/tìm kiếm**: **`23%`** ca lỗi của ReAct đến từ kết quả tìm kiếm rỗng hoặc không hữu ích làm suy luận bị trật hướng.
  3. **Hạn chế bối cảnh thực nghiệm của nguồn**: Bài báo thử nghiệm chủ yếu trên PaLM-540B (cùng một phần GPT-3) ở các tác vụ QA, fact-checking, game văn bản và mua sắm giả lập — **không phải** hệ thống multi-agent phát triển phần mềm thực tế; do đó chỉ rút nguyên lý vòng lặp và bài học giới hạn bước, không lấy phần trăm của bài báo để suy đoán hiệu năng đề tài.

### 2.2. Anthropic — *Building effective agents*: Workflow vs Agent và giới hạn nguồn (`19/12/2024`)

- **Phân biệt kiến trúc cốt lõi** ([Anthropic, 19/12/2024](https://www.anthropic.com/engineering/building-effective-agents), tương đương link [research](https://www.anthropic.com/research/building-effective-agents) trong ghi chú):
  - **Khối nền tảng (*Augmented LLM*)**: LLM gắn thêm *retrieval*, *tools* (có thể tích hợp qua MCP) và *memory*.
  - **Workflow**: LLM và công cụ được điều phối theo **đường dẫn mã nguồn định sẵn** → dễ dự đoán, nhất quán cho tác vụ có cấu trúc rõ. Gồm 5 mẫu: *Prompt chaining* (có *gate* kiểm tra), *Routing*, *Parallelization* (*sectioning*/*voting*), *Orchestrator-workers* và *Evaluator-optimizer*. *(Trong ghi chú `#issuecomment-7109633981`, chủ dự án chọn lọc đúng 3 mẫu trực tiếp khớp đề tài: Prompt chaining, Orchestrator-workers và Evaluator-optimizer.)*
  - **Autonomous Agent**: LLM tự chủ động điều khiển quy trình và công cụ trong vòng lặp theo phản hồi thực tế (*ground truth*) từ môi trường, kèm điều kiện dừng (như số vòng tối đa) và kiểm tra sandbox/guardrails; phù hợp bài toán mở không đoán trước số bước nhưng tốn chi phí hơn và có nguy cơ **tích lũy lỗi (*compounding errors*)**.
- **Ba nguyên tắc kỹ thuật nổi bật**: (1) Giữ thiết kế đơn giản nhất có thể, chỉ tăng độ phức tạp khi đo thấy cải thiện thật; (2) Minh bạch hóa bước lập kế hoạch; (3) Thiết kế cẩn thận giao diện công cụ (*Agent-Computer Interface — ACI*).
- **Giới hạn của nguồn**: Là bài hướng dẫn kỹ thuật dựa trên kinh nghiệm thực tiễn của nhà cung cấp (tự ghi chú rằng hệ sinh thái tooling đã thay đổi kể từ tháng 12/2024), **không phải** nghiên cứu thực nghiệm đối chứng và **không** chứng minh multi-agent luôn tốt hơn single-agent.

---

## 3. Đối chiếu 4 mức tổ chức LLM (Tiêu chí Issue `#4` & Mục `2.3` kế hoạch)

| Cách tổ chức | Cơ chế điều khiển & tương tác | Điểm mạnh / Hạn chế chính | Ví dụ minh họa |
|---|---|---|---|
| **1. Chat / Một lời gọi LLM** | 1 prompt → 1 câu trả lời; không có vòng lặp công cụ và phản hồi môi trường | Nhanh, rẻ; dễ ảo giác, thiếu kiểm chứng thực thi | Yêu cầu LLM viết một hàm validation độc lập |
| **2. Workflow có LLM** | Đường đi cấp cao lập trình sẵn bằng code, có kiểm tra trung gian (*gate*) và nhánh rẽ | Dễ dự đoán, dễ kiểm soát chi phí; kém linh hoạt nếu gặp lỗi ngoài kịch bản định sẵn | Chuỗi tạo dàn ý → kiểm tiêu chí → sinh tài liệu |
| **3. Agent dùng tool (Single Agent)** | 1 LLM lặp `Thought → Action → Observation` với bộ công cụ và điều chỉnh theo phản hồi thật | Linh hoạt, neo kết quả vào công cụ/môi trường; dễ tăng chi phí, lặp bước hoặc quá tải ngữ cảnh nếu gánh quá nhiều pha | Một `Dev` tự đọc tệp, áp bản vá, chạy `pytest` rồi sửa theo log lỗi |
| **4. MAS có điều phối (*Workflow-based Coordinated MAS* — Đề tài)** | Nhiều vai trò logic tách biệt ngữ cảnh, skill, schema và quyền công cụ; điều phối tập trung qua `Orchestrator + State Machine`, có vòng phản hồi có giới hạn | Kết hợp kỷ luật quy trình SDLC, tách quyền thực thi và truy vết theo phiên bản; nhưng phát sinh chi phí bàn giao/token và **cần thực nghiệm `RQ1` để kiểm chứng so với Single Agent** | `Tester` chạy runner thật phát hiện lỗi → xuất `bug_report` → `Orchestrator` giao `Dev` sửa → `Tester` kiểm tra lại + regression (≤ 3 vòng) |

> **Khẳng định bắt buộc theo tiêu chí `R02`**: **Chỉ gọi LLM sáu lần nối tiếp với sáu tên vai trò khác nhau KHÔNG phải bằng chứng của phối hợp MAS.** Cơ chế phối hợp trong đề tài chỉ có nghĩa khi đồng thời tồn tại: (1) hợp đồng đầu ra kiểm tra bằng schema + phiên bản/hash, (2) tách quyền thực thi cứng tại `Tool Gateway` (không tin vai trò model tự khai), (3) tương tác công cụ/runner thật tạo quan sát khách quan, và (4) vòng phản hồi động `Tester → Orchestrator → Dev` (hoặc định tuyến ngược về `Requirement`/`Architecture`) có giới hạn dừng tường minh.

---

## 4. Ranh giới quyết định: Phần Model đề xuất vs Phần State Machine bắt buộc kiểm soát

Đây là lựa chọn thiết kế từ kế hoạch dự án áp dụng bài học kiểm soát vòng lặp của `ReAct` và nguyên tắc đơn giản/an toàn của `Anthropic`:

| Thành phần | Phạm vi được phép quyết định / đề xuất | Điều bị cấm / Cơ chế cưỡng chế |
|---|---|---|
| **Phần do Model (LLM) quyết định trong phạm vi bước** | Đề xuất nội dung artifact (FR/NFR, thiết kế, DAG task, mã nguồn, test phát triển, nhận xét review); trong vai trò có công cụ như `Dev`/`Tester`, chủ động chọn tệp cần đọc, đề xuất bản vá, chọn bước điều tra lỗi và đề xuất phân loại lỗi | Không tự cấp quyền công cụ; không tự vượt cổng duyệt; không tự đóng task/run chỉ bằng lời khẳng định; không sửa `evaluation/`, `skills/`, prompt hay chính sách |
| **Phần do State Machine & Host/Runtime bắt buộc kiểm soát** | Khóa thứ tự giai đoạn vĩ mô (`Requirement → Cổng duyệt 1 → Architecture → Planning → Cổng duyệt 2 → Dev ↔ Tester → Đóng gói`); kiểm tra hợp lệ JSON/Pydantic, DAG, `input_commit`/`expected_hash`; cưỡng chế danh tính vai trò và quyền ghi tại `Tool Gateway`; kiểm tra trần token/thời gian/tool call và **tối đa 3 vòng sửa/task**; xử lý `cancel`, `pending_recovery`, `needs_human_review` và lưu vết/checkpoint | Mọi đề xuất chuyển bước sai luật, phê duyệt cũ (*stale approval*), gọi tool ngoài quyền/allowlist hoặc vượt quota đều bị chặn cứng ở tầng mã nguồn bất kể đầu ra LLM |

---

## 5. Ví dụ minh họa một vòng `Dev` đọc mã, gọi tool, quan sát test và điều chỉnh

> **Ranh giới bằng chứng**: Đây là **ví dụ minh họa khái niệm** cho một lượt làm việc của `Dev Agent` trên `TASK-03` (bài toán mẫu `A1` — API thêm công việc), **KHÔNG phải log chạy thật hay bằng chứng hệ thống đã triển khai**.

1. **Ngữ cảnh đầu vào**: `Orchestrator` giao `TASK-03` (`in_progress`) kèm `FR-T01` (*từ chối tiêu đề rỗng hoặc chỉ chứa khoảng trắng*), hợp đồng `POST /tasks` và giới hạn quota/quyền chỉ ghi trong `app/`.
2. **Vòng 1 — Đọc mã (*Thought → Action → Observation*)**:
   - *Thought*: Cần xem cấu trúc mã hiện tại của router và schema `Task` trước khi sửa.
   - *Action*: Đề xuất `workspace.list_files` và `workspace.read_file("app/backend/schemas.py")` → `Tool Gateway` xác thực quyền `Dev` → MCP server trả nội dung tệp.
   - *Observation*: Tệp hiện mới khai báo `title: str` (chưa chặn chuỗi chỉ có khoảng trắng).
3. **Vòng 2 — Áp bản vá & tự kiểm tra (*Action → Observation*)**:
   - *Thought*: Bổ sung kiểm tra `title` tối thiểu 1 ký tự sau khi `.strip()` và chạy suite kiểm tra phát triển.
   - *Action*: Gọi `workspace.apply_patch` (gắn `task_id`, `input_commit`, `expected_hash`) → Host tạo commit checkpoint `C1`; tiếp đó gọi `tests.run_suite(suite_id="api_dev")`.
   - *Observation*: Runner cô lập trả `exit_code = 1`: 1 ca kiểm tra báo lỗi `POST /tasks` với `"   "` trả `500` thay vì `422` do đặt sai hàm validator trong Pydantic.
4. **Vòng 3 — Điều chỉnh theo phản hồi thật (*Thought → Action → Observation → Dừng bước*)**:
   - *Thought*: Dựa vào traceback thật từ runner, sửa validator đúng chuẩn để trả `422 Unprocessable Entity` khi `title.strip() == ""`.
   - *Action*: Gọi `workspace.apply_patch` tạo commit `C2`, chạy lại `tests.run_suite(suite_id="api_dev")`.
   - *Observation*: Runner trả `exit_code = 0` (`passed`, `failed = 0`).
5. **Bàn giao có kiểm soát**: `Dev` xuất `DevResult` gắn commit `C2` và report runner → State Machine kiểm tra schema và chuyển `TASK-03` sang `waiting_test` để `Tester Agent` kiểm tra độc lập (Dev **không** tự đánh dấu `done`). Nếu quá giới hạn số bước/tool call nội bộ hoặc vượt 3 vòng sửa sau `Tester`, State Machine tự chặn và chuyển `blocked` / `needs_human_review`.

---

## 6. Phiếu nguồn, đối chiếu tiêu chí `R02` và điểm còn mở

### 6.1. Phiếu nguồn của `R02` (đầu vào cho `R10`)

| # | Nguồn & đường dẫn | Phiên bản / Ngày công bố | AI đối chiếu | Xác nhận tự đọc của chủ dự án | Phạm vi dùng & giới hạn |
|---|---|---|---|---|---|
| 1 | **Yao et al.**, *ReAct: Synergizing Reasoning and Acting in Language Models* — [arXiv HTML v3](https://arxiv.org/html/2210.03629v3) ([abstract](https://arxiv.org/abs/2210.03629)) | `arXiv:2210.03629v3`, 10/03/2023 (ICLR 2023; `[2]` trong kế hoạch) | Đã đọc toàn văn (`24/11/2026`) | Chủ dự án đã tóm tắt lý do kết hợp & nêu `Thought/Action/Observation` tại `#issuecomment-7109633981`; chờ tự xác nhận phạm vi/ngày đọc | Vòng `Thought–Action–Observation`, Bảng 2 phân tích lỗi (`0%` hallucination, `47%` reasoning error/lặp bước, `23%` search error); không suy trực tiếp sang hiệu năng đề tài |
| 2 | **Anthropic** (Erik S. & Barry Zhang), *Building effective agents* — [Engineering](https://www.anthropic.com/engineering/building-effective-agents) ([link trong ghi chú](https://www.anthropic.com/research/building-effective-agents)) | Công bố `19/12/2024` (`[7]` trong kế hoạch) | Đã đọc toàn văn (`24/11/2026`) | Chủ dự án đã trích định nghĩa Workflow/Agent & 3 mẫu workflow tại `#issuecomment-7109633981`; chờ tự xác nhận ngày đọc | Phân biệt Workflow vs Agent, 5 mẫu workflow, ACI và nguyên tắc đơn giản; là hướng dẫn kỹ thuật, không phải bằng chứng thực nghiệm |
| 3 | **Kế hoạch nghiên cứu đề tài**, `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (mục `2.1`, `2.3`) | 17/11/2026; SHA256 `975228EA…C9F` | Đã đối chiếu (`23–24/11/2026`) | Đã chốt phạm vi tại `P01` | Chuẩn hóa bảng 4 mức tổ chức LLM và ranh giới Model vs State Machine trong MVP |

### 6.2. Bảng đối chiếu tiêu chí hoàn thành Issue `#4 [R02]`

| Tiêu chí trong Issue `#4 [R02]` | Đáp ứng trong `R02/bao_cao_R02.md` | Trạng thái |
|---|---|---|
| Đọc *ReAct* và *Building effective agents*; ghi vòng hành động–quan sát và giới hạn nguồn | Mục `2.1`, `2.2` và `6.1` (đủ cơ chế vòng lặp, số liệu Bảng 2 và giới hạn của cả 2 nguồn) | Đã trình bày — chờ chủ dự án rà soát |
| Đối chiếu chat một lần, workflow có LLM, agent dùng tool và MAS có điều phối | Mục `3` (bảng so sánh 4 mức tổ chức kèm ví dụ và ưu/nhược điểm) | Đã trình bày — chờ rà soát |
| Mô tả phần do model quyết định và phần state machine bắt buộc kiểm soát | Mục `4` (bảng phân tách ranh giới Model đề xuất vs State Machine/Host cưỡng chế) | Đã trình bày — chờ rà soát |
| Có ví dụ một `Dev` đọc mã, gọi tool, quan sát test rồi điều chỉnh | Mục `5` (ví dụ 5 bước gắn nhãn minh họa khái niệm, không phải log chạy thật) | Đã trình bày — chờ rà soát |
| Không dùng việc gọi LLM sáu lần làm bằng chứng duy nhất của phối hợp | Khẳng định tường minh tại Mục `3` kèm 4 điều kiện cấu thành cơ chế phối hợp | Đạt về mặt nội dung — chờ rà soát |

### 6.3. Điểm còn mở & Nhật ký hỗ trợ AI

- **Điểm cần chủ dự án tự kiểm tra trước khi nghiệm thu**:
  1. Trong `#issuecomment-7109633981`, chủ dự án ghi chú *"(Đã đọc khó viết và trình bày ra)"* ở phần `Thought/Action/Observation` và chưa tự viết ví dụ `Dev` + bảng 4 mức tổ chức trong comment — chủ dự án cần đọc lại Mục `2`, `3`, `4`, `5` để bảo đảm tự giải thích trôi chảy bằng lời mình trước khi xác nhận nghiệm thu.
  2. Chủ dự án cần xác nhận ngày/phạm vi tự đọc thực tế của hai nguồn trên, cũng như xác nhận lại trạng thái nghiệm thu `R01` trên sổ cái `R10`.
  3. Các chi tiết định lượng ngưỡng dừng (số vòng/tool call tối đa mỗi bước, trần token toàn run) sẽ được đặc tả chính thức ở `D08` và hiệu chỉnh qua 3 run pilot ở `E04`.
- **Nhật ký hỗ trợ AI**:
  - *Đầu vào*: Bình luận `#issuecomment-7109633981` trên Issue `#4`, toàn văn `arXiv:2210.03629v3`, toàn văn Anthropic `Building effective agents`, và `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (mục `2.1`, `2.3`).
  - *Phạm vi hỗ trợ*: Anti tạo nhánh `R02` từ `main` (`8c2fe71`), biên soạn bản báo cáo ngắn `R02/bao_cao_R02.md` mở rộng và chuẩn hóa từ ghi chú của chủ dự án cho đủ tiêu chí Issue `#4`, sau đó cập nhật mục theo dõi chờ nghiệm thu tại `R10`.
  - *Giới hạn*: Báo cáo chưa có nghiệm thu của chủ dự án, không tự đánh dấu hoàn thành `R02` hay `R10` và không chứa dữ liệu thực thi thật.
