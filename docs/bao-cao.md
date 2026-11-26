# Hệ thống Multi-Agent hỗ trợ quy trình phát triển phần mềm

Bản thảo B01 cho phần 1 và 2 của báo cáo chuyên đề. Phạm vi và phương pháp lấy theo [đề cương P01 đã duyệt](ke-hoach.md). Số liệu của nguyên mẫu sẽ được bổ sung sau khi có các run thực nghiệm.

## 1. Giới thiệu

### 1.1. Bài toán, mục tiêu và phạm vi

Một ứng dụng quản lý công việc có yêu cầu “không cho lưu công việc thiếu tiêu đề”. Nếu tài liệu yêu cầu ghi quy tắc này nhưng kế hoạch lập trình bỏ sót nó, mã nguồn có thể lưu dữ liệu sai. Một bộ test chỉ kiểm tra trường hợp tiêu đề hợp lệ vẫn sẽ báo đạt. Người đánh giá cần lần ngược từ ca kiểm thử đến đúng bản mã, nhiệm vụ và yêu cầu đã duyệt để biết lỗi phát sinh ở bước nào.

Đề tài xây dựng nguyên mẫu hỗ trợ chuỗi phân tích yêu cầu, thiết kế, lập kế hoạch, sinh mã, kiểm thử và sửa lỗi. Mỗi lần thực hiện chuỗi này gọi là một *run*. Sáu vai trò logic tham gia cùng một run gồm Orchestrator, Requirement, Architecture, Planning, Dev và Tester. Người dùng duyệt hai lần, sau bản yêu cầu và sau bộ thiết kế kèm kế hoạch. Người dùng cũng quyết định nghiệm thu sản phẩm cuối.

Đối tượng khảo sát là cách sáu vai trò phối hợp và chất lượng ứng dụng đầu ra. Phạm vi thử gồm ba ứng dụng CRUD nhỏ. A1 quản lý công việc, A2 quản lý ghi chú có nhãn và A3 quản lý kho. Mỗi bài có mười tiêu chí chấp nhận độc lập. Nền tảng chạy trên máy cục bộ, dùng FastAPI, React, SQLite, Git và một worker xử lý tuần tự. Các vai trò dùng chung model, mỗi vai trò nhận ngữ cảnh, quyền công cụ và hướng dẫn phù hợp. [P01, mục 2–5](ke-hoach.md)

### 1.2. Câu hỏi nghiên cứu và phương pháp trả lời

| Mã | Câu hỏi | Dữ liệu cần thu |
| --- | --- | --- |
| RQ1 | Sáu vai trò có làm tăng mức đáp ứng yêu cầu so với một agent trong cùng điều kiện không? | Chạy cả hai cấu hình trên cùng ba bài, ba lần lặp cho mỗi cấu hình. Giữ nguyên model, brief, công cụ và trần tài nguyên toàn run. Đối chiếu kết quả build, tiêu chí độc lập, thời gian và usage của cả 18 run. |
| RQ2 | Skill ảnh hưởng thế nào đến độ đầy đủ của sản phẩm trung gian và lỗi bàn giao? | Chấm từng artifact theo rubric 0/1/2, ghi lỗi schema và thiếu tham chiếu. Nếu ngân sách được duyệt, đối chiếu ba run A3 sáu vai trò có skill với ba run A3 sáu vai trò tắt skill. |
| RQ3 | Tích hợp MCP có đáp ứng được yêu cầu về giao diện công cụ, kiểm soát quyền và truy vết không? | Chạy discovery/call thật qua SDK, kiểm tra đối số, quyền và timeout, đối chiếu log hai đầu và đo thời gian gọi. |

Quy trình nghiên cứu gồm ba bước. Đầu tiên, đối chiếu các mô hình phối hợp và công cụ với bài toán. Tiếp theo, xây dựng nguyên mẫu theo từng lát chạy được và lưu bằng chứng ở mỗi lần bàn giao. Sau ba lượt pilot, người thực hiện chốt protocol và cấu hình đo trước khi thu kết quả chính. Một run thất bại vẫn nằm trong mẫu số. Kết quả dự kiến bàn giao gồm nguyên mẫu, chuỗi bằng chứng từ yêu cầu đến test, bộ tiêu chí độc lập và số liệu so sánh có thể tính lại. [P01, mục 2, 7 và 8](ke-hoach.md)

## 2. Cơ sở lý thuyết và công nghệ

### 2.1. Từ agent đến quy trình sáu vai trò

Agent có thể quan sát môi trường, lựa chọn hành động và điều chỉnh sau khi nhận phản hồi. Trong quy trình này, Dev đọc phiên bản tệp hiện tại, đề xuất bản vá và dùng kết quả kiểm thử để quyết định bước tiếp theo. ReAct là một tiền lệ cho việc xen kẽ suy luận và hành động khi có phản hồi từ môi trường. Ta có thể kiểm tra vòng lặp qua đầu vào, lệnh gọi công cụ, kết quả và bản vá kế tiếp. [Wooldridge & Jennings, 1995](https://www.cs.ox.ac.uk/people/michael.wooldridge/pubs/ker95/ker95-html.html) · [Yao và cộng sự, 2023](https://arxiv.org/abs/2210.03629)

Trong workflow, một phần thứ tự xử lý được xác định trước. MVP giao các quyết định bắt buộc như đợi duyệt, giữ hạn mức và chuyển trạng thái cho state machine Python. Model có thể đề xuất cách thực hiện trong phạm vi vai trò. Chẳng hạn, Dev được chọn tệp cần đọc để xử lý một task. Orchestrator chỉ đưa task sang bước tiếp theo khi đủ điều kiện và có bằng chứng. [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) · [P01, mục 3–5](ke-hoach.md)

Trong vòng đời phát triển phần mềm (SDLC), kết quả của bước trước là đầu vào cho bước sau. Requirement ghi yêu cầu và câu hỏi cần làm rõ. Architecture dùng bản yêu cầu đã duyệt để mô tả dữ liệu và API. Planning chia thiết kế thành các task có phụ thuộc. Dev tạo bản vá cho từng task. Tester kiểm tra bản mã tương ứng và gửi báo lỗi có bước tái hiện, đầu vào cùng log khi cần sửa. Orchestrator theo dõi trạng thái và chuyển việc giữa các bước. Ví dụ ở A1, yêu cầu tiêu đề bắt buộc phải đi tới kiểm tra đầu vào của API và một ca test gửi tiêu đề rỗng. Đây là ví dụ thiết kế để lần theo chuỗi bàn giao. [Bản tổng hợp R01](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3#issuecomment-7104514172)

### 2.2. Những công trình liên quan đến cách phối hợp và đánh giá

| Công trình | Cơ chế được mô tả | Phần áp dụng và giới hạn |
| --- | --- | --- |
| MetaGPT | Mã hóa quy trình thao tác chuẩn (SOP) vào các bước làm việc của những vai trò chuyên môn. | Bàn giao có cấu trúc từ yêu cầu sang thiết kế và kế hoạch giúp kiểm tra đầu vào của bước kế tiếp. MVP tự xác định sáu vai trò và schema. [Hong và cộng sự](https://arxiv.org/abs/2308.00352) |
| ChatDev | Dùng chuỗi hội thoại để tổ chức trao đổi ở các giai đoạn và cho phép hỏi thêm khi chỉ dẫn còn mơ hồ. | Khi báo lỗi thiếu dữ kiện, Dev có thể yêu cầu Tester bổ sung đầu vào hay log rồi mới sửa. Khả năng sửa đúng phải được kiểm tra lại trên bản mã mới. [Qian và cộng sự](https://aclanthology.org/2024.acl-long.810/) |
| SWE-bench | Giao một issue thực tế cùng kho mã có sẵn và đánh giá thay đổi phần mềm. | Đề tài tham khảo cách đánh giá bằng thực thi. A1–A3 là bài sinh ứng dụng mới có bộ nghiệm thu riêng, nên phải báo cáo kết quả theo tiêu chí của từng bài. [Jimenez và cộng sự](https://proceedings.iclr.cc/paper_files/paper/2024/hash/edac78c3e300629acfe6cbe9ca88fb84-Abstract-Conference.html) |

SWE-agent xuất hiện trong danh mục của kế hoạch ban đầu. Chủ dự án đã rút phần nghiên cứu này khỏi phạm vi tại R05. [Quyết định tại R05](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/7#issuecomment-7170813166)

### 2.3. MCP, skill và nền tảng thực thi

MCP định nghĩa cách client và server trao đổi khả năng và gọi công cụ. Trong MVP, host giữ ngữ cảnh tin cậy gồm vai trò, run và bước hiện tại. Gateway dùng ngữ cảnh đó để kiểm tra quyền. Client gửi yêu cầu qua stdio tới local MCP server. Một yêu cầu chạy kiểm thử phải xác định suite đã cho phép. Runner thực thi suite và trả báo cáo gắn với commit đã kiểm tra. Đây là đường đi cần xác minh ở V02. [Kiến trúc MCP](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture) · [SDK Python chính thức](https://github.com/modelcontextprotocol/python-sdk)

Một skill đóng gói hướng dẫn công việc trong tệp `SKILL.md`, kèm tài nguyên khi cần. Chẳng hạn, hướng dẫn dành cho Tester có thể nhắc phải lưu bước tái hiện, đầu vào và phiên bản mã trong báo lỗi. Host vẫn quyết định công cụ nào Tester được gọi. Ghi phiên bản và hash của skill giúp người đọc nối đầu ra với đúng bộ hướng dẫn được dùng trong run. [Agent Skills Specification](https://agentskills.io/specification) · [P01, mục 3](ke-hoach.md)

API FastAPI nhận yêu cầu tạo run và trả mã định danh. Worker lấy việc từ hàng đợi bền để việc đóng trình duyệt không làm mất job. SQLite lưu metadata, các tệp artifact có phiên bản và hash trên đĩa. Pydantic kiểm tra cấu trúc đầu ra trước các kiểm tra nghiệp vụ như phiên bản tham chiếu và phụ thuộc giữa các task. pytest có thể xuất JUnit XML để lưu số ca chạy, lỗi hoặc bỏ qua. Người nghiệm thu cần mở cả báo cáo lẫn commit tương ứng. Đặc tính của các thư viện này cung cấp cơ sở triển khai, kết quả chạy thực tế sẽ nằm ở phần 4 và 5. [FastAPI](https://fastapi.tiangolo.com/tutorial/background-tasks/) · [SQLite](https://www.sqlite.org/whentouse.html) · [Pydantic](https://docs.pydantic.dev/latest/concepts/models/) · [pytest](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files)

### Ghi nhận và kiểm tra bản thảo

Codex biên soạn bản thảo ngày 26/11/2026 theo P01, bình luận R01–R05 và các nguồn đã liên kết. Chủ dự án rà soát lời giải thích và bổ sung quy định trích dẫn của trường trước khi nghiệm thu B01. [Phiếu nguồn và nhật ký R10](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/d4165793fbc54f70c54cfc19c5b41978f555eb40/docs/nguon-va-bang-chung.md)

Kiểm tra nhanh bằng `git grep -n "^| RQ" -- docs/bao-cao.md`, kết quả phải có đúng ba dòng RQ1, RQ2 và RQ3. Đối chiếu từng dòng với mục 2 của [P01](ke-hoach.md).
