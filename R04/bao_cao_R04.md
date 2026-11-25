# BÁO CÁO NGHIÊN CỨU NGẮN CÔNG VIỆC R04

> **Mã công việc**: `R04` ([GitHub Issue #6](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/6), thuộc kế hoạch tổng [#1](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/1); tiền nhiệm: [`R03` (#5)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/5))  
> **Loại công việc**: Tìm hiểu · **Tuần tương đối**: Tuần 2  
> **Nhánh lưu trữ**: `R04` trên kho `DaoNgocDinh/ChuyenDeKTPM` (khởi tạo từ nền `main` commit `8c2fe71`)  
> **Ngày lập báo cáo**: 25/11/2026  
> **Trạng thái**: Đã lập bản báo cáo nhỏ `R04` trên nhánh riêng `R04` — **chờ chủ dự án rà soát và quyết định nghiệm thu** (chưa đóng Issue `#6`, chưa chuyển vào danh sách đã hoàn thành của sổ cái `R10`)  
> **Nguồn chuẩn đối chiếu**: `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (17/11/2026; SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`), mục `2.4–2.5`, `3.4`, `3.7`  
> **Đầu vào ghi chú của chủ dự án**: [Bình luận đợt 1 `#issuecomment-7167694255` (`23:13`, 25/11/2026 GMT+7)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/6#issuecomment-7167694255) và [bản chuẩn hóa `#issuecomment-7167728123` (`23:15`, 25/11/2026 GMT+7)](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/6#issuecomment-7167728123)  
> **Ranh giới báo cáo**: Đây là bản báo cáo ngắn phục vụ nghiệm thu riêng công việc **`R04`**, tách bạch rõ: (a) ghi chú của chủ dự án, (b) nội dung đối chiếu trực tiếp từ bài báo gốc **ChatDev — ACL 2024** (`2024.acl-long.810`, pp. 15174–15186), (c) tính năng phát triển về sau trên kho `OpenBMB/ChatDev`, và (d) đề xuất thiết kế cấu trúc bàn giao bug `Tester → Dev` trong MVP. Báo cáo **không** nhận số liệu bài báo làm kết quả đề tài và **không** chứa dữ liệu chạy thật (`RQ1`–`RQ3` giữ mở).

---

## 1. Mục tiêu, tiền nhiệm và dấu vết ghi chú của chủ dự án

- **Mục tiêu (Issue `#6`)**: Hiểu cách các vai trò giao tiếp trong **ChatDev (ACL 2024)**, đối chiếu với **MetaGPT (`R03`)**, chỉ rõ giới hạn của hội thoại tự nhiên và thiết kế thông tin bàn giao lỗi giữa **`Tester`** và **`Dev`**.
- **Tình trạng tiền nhiệm (`R03` — `#5`)**: Đã có báo cáo [`R03/bao_cao_R03.md`](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/07148516d90f66ba6ddefe448c5a264bf5061a95/R03/bao_cao_R03.md) tại commit `0714851` trên nhánh `R03`; Issue `#5` đã đóng trên GitHub (`25/11/2026`) nhưng vẫn chờ chủ dự án xác nhận nghiệm thu báo cáo trên sổ cái `R10`.
- **Diễn biến ghi chú của chủ dự án trên Issue `#6`**:
  1. **Đợt 1 (`#issuecomment-7167694255`)**: Nêu khung phát triển phần mềm dựa trên hội thoại của ChatDev theo mô hình thác nước gồm `chat chain` ($\mathcal{C}$), 3 pha tuần tự ($\mathcal{P}$: thiết kế, lập trình, kiểm thử), các nhiệm vụ con ($\mathcal{T}$) và cơ chế `communicative dehallucination` (chủ động hỏi chi tiết hơn thay vì tự suy đoán). *(Lưu ý thuật ngữ: thống nhất dịch `communicative dehallucination` là **khử/giải ảo giác giao tiếp**, tránh cụm "giải mã giao tiếp" ở câu mở đầu.)*
  2. **Đợt 2 (`#issuecomment-7167728123`)**: Diễn đạt gọn và rõ hướng áp dụng vào đề tài: mượn nguyên lý của *communicative dehallucination* để khi báo lỗi chưa rõ, **`Dev`** yêu cầu **`Tester`** bổ sung bước tái hiện, đầu vào và log trước khi sửa mã và kiểm thử lại.
- **Phần bổ sung từ đối chiếu toàn văn nguồn gốc**: Hai bình luận gốc chưa nêu chi tiết mô hình 5 vai trò/5 subtask, bộ nhớ ngắn/dài hạn, bộ dữ liệu `SRDD` & metrics đánh giá, bảng so sánh ChatDev vs MetaGPT, đặc tả đầy đủ thông tin `bug_report` và ranh giới giữa bài báo ACL 2024 với các tính năng repo về sau. Các mục `2`–`6` dưới đây bổ sung đầy đủ từ toàn văn ACL 2024 PDF và README `OpenBMB/ChatDev` để chủ dự án rà soát.

---

## 2. Tóm tắt ChatDev — ACL 2024 (`2024.acl-long.810`, pp. 15174–15186)

### 2.1. Mô hình vai trò, Chat Chain, Bộ nhớ và Khử ảo giác giao tiếp

- **Bài toán & ý tưởng lõi** *(Abstract, Sec. 1, pp. 15174–15175)*: Các phương pháp học sâu trước đó xử lý rời rạc từng pha thác nước gây đứt gãy kỹ thuật; ChatDev dùng **ngôn ngữ làm cầu nối thống nhất** để nhiều agent chuyên biệt hợp tác qua hội thoại nhiều lượt, đồng thời kiểm soát hiện tượng **ảo giác lập trình (*coding hallucinations*)** — mã chưa hoàn thiện (*placeholder*), không chạy được hoặc lệch yêu cầu.
- **Kiến trúc `Chat Chain` (3 pha · 5 subtask · 5 vai trò cặp đôi)** *(Sec. 3.1, Fig. 2, Sec. 4 Implementation Details, pp. 15176–15179)*:
  - Chuỗi $\mathcal{C} = \langle \mathcal{P}^1, \mathcal{P}^2, \mathcal{P}^3 \rangle$ đi tuần tự qua 3 pha (**Design → Coding → Testing**), phân rã thành **5 subtask**:
    1. `Design`: `CEO` (Instructor $\mathcal{I}$) ↔ `CTO` (Assistant $\mathcal{A}$) → thống nhất ý tưởng thiết kế (`{ideas}`).
    2. `Coding`: `CTO` ($\mathcal{I}$) ↔ `Programmer` ($\mathcal{A}$) → sinh mã nguồn ban đầu (`{code}`).
    3. `Code Complete`: `CTO` ($\mathcal{I}$) ↔ `Programmer` ($\mathcal{A}$) → hoàn thiện các đoạn mã thiếu/placeholder.
    4. `Code Review` (*kiểm thử tĩnh*): `Reviewer` ($\mathcal{I}$) ↔ `Programmer` ($\mathcal{A}$) → rà soát mã qua đối thoại.
    5. `Testing` (*kiểm thử động*): `Tester` ($\mathcal{I}$) ↔ `Programmer` ($\mathcal{A}$) → chạy biên dịch/thực thi trên `Python 3.11.4` và gỡ lỗi theo phản hồi trình thông dịch.
  - **Cơ chế nhị nguyên & điều kiện dừng**: Mỗi subtask chỉ có đúng **2 agent** ($\mathcal{I}$ giao chỉ dẫn $\to$, $\mathcal{A}$ đề xuất giải pháp $\leadsto$) nhằm tránh topo giao tiếp phức tạp; dùng **Inception Prompting** ($\mathsf{P}_I, \mathsf{P}_A$) chống đảo vai (*role flipping*), lặp chỉ dẫn (*instruction repeating*) và phản hồi giả (*fake replies*). Subtask dừng khi có **2 lượt sửa mã không đổi**, chạm trần **10 vòng hội thoại**, hoặc trợ lý phát dấu hiệu `<SOLUTION>`.
  - **Phân tầng bộ nhớ** *(Sec. 3.1 Memory, Eq. 3–5, p. 15177)*: **Short-term memory** ($\mathcal{M}_t^i$) lưu các lượt hội thoại trong pha hiện hành; **Long-term memory** ($\tilde{\mathcal{M}}^i$) chỉ rút trích và truyền **giải pháp cuối** $\tau(\cdot)$ của các pha trước sang pha kế tiếp để tránh tràn ngữ cảnh.
- **Cơ chế `Communicative Dehallucination` (CDH)** *(Sec. 3.2, Eq. 6–7, p. 15178)*: Thay vì hỏi–đáp thẳng $\langle \mathcal{I}\to\mathcal{A}, \mathcal{A}\leadsto\mathcal{I}\rangle_{\circlearrowleft}$, ChatDev chèn bước **đảo vai có chủ đích** $\langle \mathcal{I}\to\mathcal{A}, \langle \mathcal{A}\to\mathcal{I}, \mathcal{I}\leadsto\mathcal{A}\rangle_{\circlearrowleft}, \mathcal{A}\leadsto\mathcal{I}\rangle_{\circlearrowleft}$ để Assistant chủ động hỏi ngược Instructor thông tin cụ thể (như tên thư viện, lớp/hàm cần sửa) rồi mới xuất phản hồi chính thức. CDH được bật ở 3 subtask: `Code Complete`, `Code Review` và `Testing`.

### 2.2. Đánh giá thực nghiệm và Hạn chế trong bài báo ACL 2024 *(chỉ tham khảo nguồn)*

| Hạng mục | Nội dung từ bài báo ACL 2024 (`2024.acl-long.810`) | Vị trí nguồn |
|---|---|---|
| **Dataset & Thiết lập** | **SRDD** (*Software Requirement Description Dataset*): **1.200 prompt** chia 5 lĩnh vực (`Education`, `Work`, `Life`, `Game`, `Creation`), 40 tiểu mục × 30 prompt (sinh bằng LLM + người tinh chỉnh). Chạy cùng **`ChatGPT-3.5`** (`temperature = 0.2`) và **`Python 3.11.4`** cho mọi baseline. | Sec. 4, pp. 15178–15179 |
| **Baselines & Metrics** | So với `GPT-Engineer` (single-agent) và `MetaGPT` (multi-agent SOP). Đo 4 chỉ số: **Completeness** (tỷ lệ mã không chứa *placeholder*), **Executability** (tỷ lệ biên dịch/chạy trực tiếp được), **Consistency** (cosine embedding giữa mô tả yêu cầu và mã đã bỏ comment), **Quality** (`Completeness × Executability × Consistency`); kèm chấm cặp đối chứng bằng `GPT-4` và chuyên gia người. | Sec. 4, Tables 1–2, pp. 15178–15180 |
| **Kết quả chính tác giả công bố** | • Table 1: ChatDev đạt `0.5600` Completeness, `0.8800` Executability, `0.8021` Consistency, `0.3953` Quality (vs MetaGPT `0.4834 / 0.4145 / 0.7601 / 0.1523` và GPT-Engineer `0.5022 / 0.3583 / 0.7887 / 0.1419`).  <br>• Table 2 (chấm cặp): ChatDev thắng GPT-Engineer `77.08%` (GPT-4) / `90.16%` (Human) và thắng MetaGPT `57.08%` (GPT-4) / `88.00%` (Human).  <br>• Table 3 (chi phí): ChatDev tốn `148.2s`, `22,949` token (~144 LOC), chậm và tốn token hơn hẳn GPT-Engineer (`15.6s`, `7,183` token), nhưng nhẹ hơn MetaGPT (`154.0s`, `29,279` token).  <br>• Table 4 (ablation): bỏ `Roles` làm Quality tụt mạnh nhất (`0.3953 → 0.2212`, Executability `0.88 → 0.58`); bỏ `CDH` giảm Quality còn `0.3094` và Completeness còn `0.4700`.  <br>• Sec. 4.3 (phân tích hội thoại): `57.20%` lượt trao đổi là ngôn ngữ tự nhiên, `42.80%` ngôn ngữ lập trình (riêng `Code Review` chiếm `61.09%` phần lập trình); lỗi phổ biến nhất ở review là `Method Not Implemented` (`34.85%`), ở testing là `ModuleNotFound` (`45.76%`), `NameError` và `ImportError` (mỗi loại `15.25%`). | Sec. 4.1–4.3, Tables 1–4, Figs. 3–5, pp. 15179–15182 |
| **Hạn chế tự thừa nhận** | (1) Logic sinh ra thường đơn giản, mật độ thông tin thấp (yêu cầu mơ hồ dễ sinh dữ liệu key-value tĩnh thay vì CSDL thực; chỉ phù hợp nguyên mẫu); (2) Khó tự động hóa đánh giá phần mềm tổng quát — 4 metric chưa đo đúng hành vi nghiệp vụ, độ bền, an toàn hay UX; (3) Tốn nhiều token và thời gian hơn hẳn single-agent. | Sec. 6 Limitations, p. 15182 |

> **Cảnh báo chéo giữa `R03` và `R04`**: Trên `SoftwareDev` dùng `GPT-4`, bài báo MetaGPT báo cáo MetaGPT vượt ChatDev (`3.75` vs `2.25`); ngược lại, trên `SRDD` dùng `ChatGPT-3.5` và 4 metric riêng, bài báo ChatDev báo cáo ChatDev vượt MetaGPT (`0.3953` vs `0.1523`). Độ vênh này chứng minh trực tiếp **không được lấy số liệu từ bất kỳ bài báo nào để khẳng định ưu thế hay dự đoán kết quả cho hệ thống đề tài**.

---

## 3. Đối chiếu ChatDev (ACL 2024) với MetaGPT (ICLR 2024) và Giới hạn hội thoại tự nhiên

### 3.1. Bảng so sánh có dẫn nguồn

| Tiêu chí | MetaGPT *(Hong et al., ICLR 2024 — `arXiv:2308.00352v7`)* | ChatDev *(Qian et al., ACL 2024 — `2024.acl-long.810`)* | Định hướng nguyên mẫu 6 vai trò của đề tài *(Kế hoạch 17/11/2026)* |
|---|---|---|---|
| **Mô hình vai trò** | **5 vai trò**: `Product Manager`, `Architect`, `Project Manager`, `Engineer`, `QA Engineer` *(Sec. 3.1)* | **5 vai trò** ghép từng cặp $\mathcal{I} \leftrightarrow \mathcal{A}$: `CEO`, `CTO`, `Programmer`, `Reviewer`, `Tester` *(Sec. 3.1, Fig. 2, Sec. 4)* | **Đúng 6 vai trò logic**: `Orchestrator`, `Requirement`, `Architecture`, `Planning`, `Dev`, `Tester` (gộp review & test vào `Tester`, không tách `Reviewer`) |
| **Cơ chế điều phối** | Dây chuyền SOP theo sự kiện **Shared Message Pool + Publish–Subscribe**, kích hoạt khi đủ phụ thuộc *(Sec. 3.1–3.2)* | **Chat Chain** tuyến tính 3 pha / 5 subtask kiểu thác nước; đối thoại từng cặp tối đa 10 lượt/subtask *(Sec. 3.1, Sec. 4)* | **`Orchestrator + State Machine` tập trung** (1 worker SQLite), khóa thứ tự pha, **2 cổng duyệt con người** và trần ngân sách chung |
| **Sản phẩm trung gian & giao tiếp** | **Tài liệu & sơ đồ có cấu trúc** (PRD, System Design, Interface, Flow, Task list) thay hội thoại tự do *(Sec. 3.2, App. B)* | **Hội thoại ngôn ngữ tự nhiên + mã nguồn**; chỉ rút trích chuỗi giải pháp $\tau(\cdot)$ qua dấu hiệu `<SOLUTION>` sang pha sau *(Sec. 3.1–3.2)* | **Artifact JSON/Pydantic + Markdown bất biến** có `version`, `SHA256`, `parent_refs` và kiểm tra ngữ nghĩa bằng chương trình |
| **Xử lý lỗi & phản hồi** | `Engineer` tự viết/chạy unit test (*Executable Feedback*), sửa lặp tối đa **3 lần**; sau đó `QA Engineer` sinh test/review *(Sec. 3.3)* | Tách kiểm thử tĩnh (`Reviewer ↔ Programmer`) và động (`Tester ↔ Programmer` + `Python 3.11.4`), dùng **CDH** hỏi chi tiết từng lỗi *(Sec. 3.1–3.2, 4.3)* | Vòng **`Tester → Orchestrator → Dev`** qua `bug_report.json` + runner cô lập (MCP `stdio`), tối đa **3 vòng sửa/task**; lỗi yêu cầu/thiết kế quay ngược đầu nguồn |
| **Đánh giá & kiểm chứng** | `HumanEval`, `MBPP` (`Pass@1`) + `SoftwareDev` (chấm tay Executability 1–4, Revision Cost trên 7/70 bài) *(Sec. 4)* | `SRDD` 1.200 prompt: Completeness, Executability, Consistency (cosine), Quality + chấm cặp GPT-4/Human *(Sec. 4)* | **18 run chính** (`A1–A3`, `S` vs `M` cùng trần ngân sách) chấm bằng **bộ test nghiệm thu độc lập `evaluation/`** (10 tiêu chí/bài) |

### 3.2. Giới hạn của hội thoại tự nhiên và nhu cầu bắt buộc có Schema + Test thật

1. **Rủi ro nội tại của hội thoại tự do**: Ngay trong bài ChatDev đã chỉ ra đối thoại nhiều lượt giữa LLM dễ gặp **đảo vai (*role flipping*), lặp chỉ dẫn (*instruction repeating*), phản hồi giả (*fake replies*)** *(Sec. 3.1, p. 15177)* và có xu hướng **tự ý thêm tính năng ngoài yêu cầu gốc** *(Sec. 4.1, p. 15180 — ví dụ tự tăng độ khó game hoặc thêm GUI ngoài brief)*.
2. **Chi phí tăng mạnh nhưng không đảm bảo đúng nghiệp vụ**: ChatDev tiêu thụ nhiều token/thời gian hơn gấp ~3–9 lần single-agent *(Table 3)*, trong khi 4 metric chính mới kiểm tra mã không có *placeholder*, biên dịch chạy được và độ tương đồng embedding — **không kiểm chứng được từng quy tắc nghiệp vụ** (như từ chối tiêu đề rỗng trả `422` hay từ chối xuất quá tồn kho).
3. **Kết luận thiết kế cho đề tài**: Học nguyên lý **làm rõ thông tin cụ thể từng lỗi** của ChatDev (`CDH`), nhưng **không** để `Dev` và `Tester` trò chuyện văn bản tự do nhiều lượt. Mọi phản hồi lỗi phải đóng gói qua **schema JSON/Pydantic bắt buộc** và neo vào **bằng chứng thực thi thật từ runner cô lập** (`exit_code`, JUnit XML/JSON, log, `commit_hash`).

---

## 4. Đề xuất thông tin bắt buộc khi `Tester` bàn giao bug cho `Dev`

Áp dụng bài học *communicative dehallucination* vào kiến trúc kiểm soát bằng schema của đề tài: thay vì để `Dev` phải hỏi đi hỏi lại qua nhiều lượt hội thoại vì báo lỗi mơ hồ, **State Machine kiểm tra ngay tính đầy đủ của `bug_report.json` trước khi bàn giao sang `Dev`**, đồng thời giữ cơ chế yêu cầu bổ sung có cấu trúc qua `Orchestrator` nếu vẫn thiếu dữ kiện tái hiện.

| Nhóm thông tin | Trường bắt buộc đề xuất trong `bug_report.json` | Lý do bắt buộc & quy tắc kiểm soát |
|---|---|---|
| **Định danh & Truy vết** | `bug_id`, `run_id`, `task_id`, `requirement_ids` (FR/AC bị vi phạm), `commit_hash`, `repair_round` | Neo đúng ngữ cảnh task, tiêu chí chấp nhận và bản mã bị lỗi; tránh `Dev` sửa nhầm phiên bản (*stale commit*). |
| **Phân loại & Mức độ** | `severity` (`critical` / `major` / `minor`), `root_cause_category` (`code_bug` / `requirement_gap` / `design_mismatch` / `dev_test_bug` / `runner_env_error`) | Giúp `Orchestrator` định tuyến đúng: chỉ `code_bug` chuyển về `Dev`; lỗi yêu cầu/thiết kế quay về `Requirement`/`Architecture`; lỗi hạ tầng không đổ cho `Dev`. |
| **Tái hiện & Sai lệch** | `reproduction_steps` (bước cụ thể), `input_payload` / dữ liệu biên, `expected_behavior`, `actual_behavior` | Triệt tiêu chỉ dẫn chung chung kiểu *"API bị lỗi"* — chính là nguồn gốc ảo giác mã mà ChatDev phải dùng CDH để hỏi ngược lại. |
| **Bằng chứng thực thi thật** | `suite_id`, `test_case_id`, `exit_code`, `runner_report_uri`, `error_excerpt` (traceback/log rút gọn đã lọc secret) | Cấm `Tester` báo lỗi chỉ bằng nhận xét suy đoán của LLM; bảo đảm `Dev` bám sát quan sát thực tế từ runner (`NFR07`). |
| **Phạm vi gợi ý & Yêu cầu làm rõ** | `suspected_files` (tùy chọn), `clarification_request` (trường có cấu trúc nếu `Dev` phát hiện bằng chứng mâu thuẫn hoặc thiếu đầu vào tái hiện) | `Tester` không được sửa `app/`; nếu `Dev` cần làm rõ như tinh thần CDH thì gửi tín hiệu cấu trúc qua `Orchestrator` (tính chung vào quota, không mở chat tự do vô hạn). |

- **Luật dừng & hồi quy**: Sau khi `Dev` áp bản vá mới (commit mới) và tự kiểm tra, `Tester` phải chạy lại **cả ca lỗi vừa báo lẫn kiểm thử hồi quy (*regression*)**. Giới hạn cứng **tối đa 3 vòng sửa/task**; vượt ngưỡng chuyển `blocked` và `needs_human_review`.

---

## 5. Phân biệt bài báo ACL 2024 với tính năng kho `OpenBMB/ChatDev` phát triển về sau

*(Xác minh trực tiếp đối chiếu PDF [`2024.acl-long.810`](https://aclanthology.org/2024.acl-long.810.pdf) với README kho [`OpenBMB/ChatDev`](https://github.com/OpenBMB/ChatDev) ngày 25/11/2026.)*

| Mốc / Phạm vi | Nội dung thực tế có mặt | Lưu ý khi trích dẫn trong báo cáo đề tài |
|---|---|---|
| **Bài báo gốc ACL 2024** (`2024.acl-long.810`, 08/2024; `arXiv:2307.07924v5`, 06/2024) | 3 pha / 5 subtask cố định (`Design`, `Coding`, `Code Complete`, `Code Review`, `Testing`), 5 vai trò (`CEO`, `CTO`, `Programmer`, `Reviewer`, `Tester`), `Chat Chain`, `Inception Prompting`, `Short/Long-term Memory`, `Communicative Dehallucination`, bộ `SRDD` 1.200 prompt, chạy trên `ChatGPT-3.5` + `Python 3.11.4`. | **Đây là phạm vi duy nhất được trích dẫn dưới mục `[4]` (Qian et al., ACL 2024).** |
| **Mở rộng nhánh `chatdev1.0` (09/2023–11/2023, sau preprint 07/2023)** | **Art mode** (Designer sinh ảnh, 09/2023), **Human-Agent-Interaction** (người đóng vai Reviewer, 09/2023), **Git mode** (`git_management`, 09/2023), **Docker execution** (10/2023), **Incremental development** (sửa mã có sẵn, 11/2023), bổ sung pha `Documenting` trong repo. | Là tính năng kỹ thuật bổ sung trên repo `chatdev1.0`, **không** nằm trong mô hình đánh giá của bài báo ACL 2024. |
| **Nghiên cứu kế tiếp trên repo (2024–2025)** | **Experiential Co-Learning (ECL)** (01/2024, `arXiv:2312.17025`), **Iterative Experience Refinement (IER)** (05/2024, `arXiv:2405.04219`), **MacNet** — topo DAG hỗ trợ >1.000 agent (nhánh `macnet`, 06/2024, `arXiv:2406.07155`), **Evolving Orchestration / Puppeteer** điều phối bằng RL (nhánh `puppeteer`, NeurIPS 2025, `arXiv:2505.19591`). | Thuộc các bài báo/nhánh nghiên cứu riêng biệt công bố sau, **không** gộp vào kết quả bài ACL 2024. |
| **ChatDev 2.0 — DevAll (01/2026)** | Chuyển thành **nền tảng zero-code đa tác tử tổng quát** (Web Console Vue 3, cấu hình workflow YAML, Docker Compose, tích hợp OpenClaw) cho mọi kịch bản (3D, phân tích dữ liệu, deep research…); đẩy bản cổ điển về nhánh `chatdev1.0`. | Hoàn toàn khác định vị công ty phần mềm 3 pha của bài ACL 2024; tuyệt đối không trích nhầm khi phân tích `[4]`. |

---

## 6. Phiếu nguồn, đối chiếu tiêu chí `R04` và điểm còn mở

### 6.1. Phiếu nguồn của `R04` (đầu vào cho `R10`)

| # | Nguồn & đường dẫn | Phiên bản / Xuất bản | AI đối chiếu | Xác nhận tự đọc của chủ dự án | Phạm vi dùng & giới hạn |
|---|---|---|---|---|---|
| 1 | **C. Qian et al.** (Zhiyuan Liu, Maosong Sun), *ChatDev: Communicative Agents for Software Development* — [ACL Anthology](https://aclanthology.org/2024.acl-long.810/) · [PDF](https://aclanthology.org/2024.acl-long.810.pdf) · [arXiv HTML v5](https://arxiv.org/html/2307.07924) | **ACL 2024** (Vol. 1: Long Papers, pp. 15174–15186, 08/2024; DOI `10.18653/v1/2024.acl-long.810`; `arXiv:2307.07924v5`, 05/06/2024; `[4]` trong kế hoạch) | Đã đọc toàn văn PDF & HTML (`25/11/2026`) | Chủ dự án đã tóm tắt `Chat Chain` & `Communicative Dehallucination` tại `#issuecomment-7167694255`, `#issuecomment-7167728123`; chờ tự xác nhận phạm vi/ngày đọc chi tiết Sec. 4 & 6 | Mô hình 3 pha/5 subtask/5 vai trò, bộ nhớ, CDH, bộ `SRDD`, 4 metrics, ablation & hạn chế Sec. 6; không lấy số liệu làm kết quả đề tài |
| 2 | **Kho mã nguồn `OpenBMB/ChatDev`** — [GitHub README](https://github.com/OpenBMB/ChatDev) | Kiểm tra trực tiếp ngày `25/11/2026` (nhánh `main` ChatDev 2.0 & lịch sử `chatdev1.0`, `macnet`, `puppeteer`) | Đã đối chiếu README (`25/11/2026`) | Chờ chủ dự án rà soát | Chỉ dùng để tách rạch ròi tính năng phát triển về sau khỏi nội dung bài báo ACL 2024 |
| 3 | **MetaGPT** (`arXiv:2308.00352v7`) & **Kế hoạch nghiên cứu** (`17/11/2026`, SHA256 `975228EA…C9F`) | Đã đối chiếu tại `R03` (`0714851`) | Đã đối chiếu (`25/11/2026`) | Đã chốt phạm vi tại `P01` | Dùng cho bảng so sánh ChatDev vs MetaGPT và đối chiếu hợp đồng `bug_report` trong MVP |

### 6.2. Bảng đối chiếu tiêu chí hoàn thành Issue `#6 [R04]`

| Hạng mục / Tiêu chí trong Issue `#6 [R04]` | Đáp ứng trong `R04/bao_cao_R04.md` | Trạng thái |
|---|---|---|
| Đọc bài ChatDev ACL 2024, ghi mô hình vai trò, trao đổi và đánh giá | Mục `2.1`, `2.2`, `6.1` (3 pha/5 subtask/5 vai trò cặp đôi, Inception Prompting, bộ nhớ, CDH, `SRDD`, 4 metrics, Tables 1–4 & Sec. 6) | Đã trình bày — chờ chủ dự án rà soát |
| Đối chiếu ChatDev với MetaGPT về điều phối, sản phẩm trung gian và xử lý lỗi | Mục `3.1` (bảng so sánh có dẫn nguồn cả 2 bài báo gốc và đối chiếu với nguyên mẫu 6 vai trò) | Đã trình bày — chờ rà soát |
| Đề xuất thông tin phải giữ khi `Tester` bàn giao bug cho `Dev` | Mục `4` (bảng 5 nhóm trường bắt buộc trong `bug_report.json` + cơ chế làm rõ có cấu trúc và luật dừng ≤3 vòng) | Đã trình bày — chờ rà soát |
| Có bảng so sánh có nguồn, nêu giới hạn hội thoại tự nhiên và nhu cầu schema/test thật | Mục `3.1` (bảng so sánh có nguồn) và Mục `3.2` (giới hạn hội thoại tự do + yêu cầu schema JSON/Pydantic & runner thật) | Đã trình bày — chờ rà soát |
| Phân biệt nội dung bài năm 2024 với tính năng repo phát triển về sau | Mục `5` (bảng đối chiếu 4 mốc: ACL 2024 vs `chatdev1.0` mở rộng vs ECL/IER/MacNet/Puppeteer vs ChatDev 2.0 DevAll) | Đã trình bày — chờ rà soát |

### 6.3. Điểm còn mở & Nhật ký hỗ trợ AI

- **Điểm cần chủ dự án tự kiểm tra trước khi nghiệm thu**:
  1. Hai bình luận gốc trên `#6` mới nêu phần `Chat Chain`, `Communicative Dehallucination` và ý tưởng áp dụng chung cho `Dev ↔ Tester`; chủ dự án cần đọc lại Mục `2.2` (đánh giá & độ vênh số liệu với MetaGPT), Mục `3` (bảng so sánh & giới hạn hội thoại tự nhiên), Mục `4` (các trường bắt buộc của `bug_report.json`) và Mục `5` (phân biệt ACL 2024 vs repo về sau) để tự giải thích trôi chảy bằng lời mình trước khi nghiệm thu.
  2. Chủ dự án cần xác nhận ngày/phạm vi tự đọc bài báo ACL 2024 (`2024.acl-long.810`); chi tiết JSON/Pydantic schema chính thức của `bug_report.json` và mã phân loại lỗi sẽ được khóa ở **`D07`/`D08`** (Tuần 3).
  3. Bước tiếp theo của cụm Tuần 2 là `R05` (SWE-agent — `#7`) và `R06` (SWE-bench — `#8`).
- **Nhật ký hỗ trợ AI**:
  - *Đầu vào*: Hai bình luận `#issuecomment-7167694255`, `#issuecomment-7167728123` trên Issue `#6`, toàn văn PDF ACL 2024 (`2024.acl-long.810.pdf`), `arXiv:2307.07924v5`, README kho `OpenBMB/ChatDev` (đọc trực tiếp ngày `25/11/2026`), `R03/bao_cao_R03.md` (`0714851`) và kế hoạch Word gốc (mục `2.4–2.5`, `3.4`, `3.7`).
  - *Phạm vi hỗ trợ*: Anti tạo nhánh `R04` từ `main` (`8c2fe71`), biên soạn bản báo cáo ngắn `R04/bao_cao_R04.md` đầy đủ tiêu chí Issue `#6`, cập nhật sổ cái `R10/so_cai_hoan_thanh.md` trên nhánh `R10` và đăng bình luận đối chiếu tại Issue `#12`.
  - *Giới hạn*: Báo cáo chưa có nghiệm thu của chủ dự án, không tự ghi thay ngày tự đọc chi tiết, không đóng Issue `#6` và không chứa dữ liệu chạy thật hay kết luận thực nghiệm.
