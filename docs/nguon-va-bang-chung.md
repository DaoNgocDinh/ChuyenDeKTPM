# R10 · Danh mục nguồn và bằng chứng

Danh mục giữ thứ tự 1–21 và URL gốc tại mục 7 của `Ke_hoach_nghien_cuu_he_thong_Multi_Agent.docx` (SHA256 `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`). Ngày 26/11/2026, Codex đối chiếu 21 trang với danh mục và ghi vị trí cần tra bên dưới. Các ghi chú về cách áp dụng là diễn giải cho đề tài. Ngày đọc của người thực hiện chỉ được ghi khi chính người đó xác nhận.

| Mã | Tác giả, nguồn | Vị trí và phiên bản | Ý dùng trong đề tài |
| --- | --- | --- | --- |
| 1 | [Wooldridge & Jennings, 1995. Intelligent Agents](https://www.cs.ox.ac.uk/people/michael.wooldridge/pubs/ker95/ker95-html.html) | § What is an Agent? DOI 10.1017/S0269888900008122. | Phân biệt thành phần có trạng thái, tương tác với môi trường và phối hợp với các thành phần khác. R01 dùng để mô tả sáu vai trò. |
| 2 | [Yao và cộng sự, ICLR 2023. ReAct](https://arxiv.org/abs/2210.03629) | Abstract, arXiv 2210.03629v3. | Quyết định tiếp theo có thể dùng quan sát từ hành động trước. R02 minh họa Dev sửa mã sau phản hồi kiểm thử. |
| 3 | [Hong và cộng sự, ICLR 2024. MetaGPT](https://arxiv.org/abs/2308.00352) | Abstract, phần SOP, arXiv 2308.00352. | SOP tổ chức các bước chuyên môn và bàn giao đầu ra trung gian. R03 và D05 dùng ý này cho bàn giao yêu cầu, thiết kế và kế hoạch. |
| 4 | [Qian và cộng sự, ACL 2024. ChatDev](https://aclanthology.org/2024.acl-long.810/) | Abstract, chat chain, communicative dehallucination. DOI 10.18653/v1/2024.acl-long.810. | Hội thoại có mục tiêu giúp vai trò hỏi thêm khi thiếu dữ kiện. R04 áp dụng cho báo lỗi Tester gửi Dev. |
| 5 | [Yang và cộng sự, NeurIPS 2024. SWE-agent](https://papers.nips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html) | Abstract, Agent-Computer Interface. | Bài báo nghiên cứu giao diện cho tác nhân tương tác với kho mã. Giữ mục thư mục gốc để đối chiếu quyết định bỏ R05. |
| 6 | [Jimenez và cộng sự, ICLR 2024. SWE-bench](https://proceedings.iclr.cc/paper_files/paper/2024/hash/edac78c3e300629acfe6cbe9ca88fb84-Abstract-Conference.html) | Abstract, nhiệm vụ chỉnh sửa kho mã từ issue. | Phân biệt bài toán sửa mã có sẵn với ba ứng dụng CRUD sinh mới trong E01. Kết quả bài báo chỉ thuộc benchmark của tác giả. |
| 7 | [Anthropic, 2024. Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | What are agents? Building blocks, workflows, and agents. | Dùng tiêu chí đường đi được xác định trước và bước do model chọn để mô tả ranh giới điều phối trong R02. |
| 8 | [GitHub. What are multi-agent systems?](https://github.com/resources/articles/what-are-multi-agent-systems) | Bảng chọn mẫu subagent, router, handoff, skills, custom workflow. | Bổ sung ví dụ thực hành về bàn giao giữa các vai trò. Việc R01 chọn điều phối tập trung thuộc thiết kế của đề tài. |
| 9 | [Syme & de Halleux, GitHub Blog, 2026-02-13. Automate repository tasks with GitHub Agentic Workflows](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/) | Phần quyền đọc mặc định và safe outputs. | Minh họa việc giới hạn thao tác ghi được duyệt trên GitHub. P01 đặt Git cục bộ trong MVP, phần GitHub tự động thuộc F04. |
| 10 | [MCP. Architecture overview](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture) | Bản 2026-07-28, host, client và server. | R07 đối chiếu cách host mở kết nối qua client tới local server. |
| 11 | [MCP. Understanding MCP servers](https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts) | Bản 2026-07-28, Core Server Features. | Tra ba khả năng tool, resource và prompt khi xác định giao diện của server. |
| 12 | [MCP. Build an MCP server](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server) | Bản 2026-07-28, hướng dẫn server và giao tiếp stdio. | Đối chiếu discovery/call và giữ stdout cho giao thức trong ví dụ R07. |
| 13 | [MCP. Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices) | Bản 2026-07-28, các rủi ro tích hợp. | Đầu vào cho D11. Kiểm chứng quyền của Gateway, phạm vi workspace và runner cần bằng chứng riêng. |
| 14 | [Model Context Protocol. Python SDK](https://github.com/modelcontextprotocol/python-sdk) | README của SDK chính thức, client/server. | R07/I14 cần lưu phiên bản package thực sự chạy và kết quả gọi tool. |
| 15 | [Agent Skills. Overview](https://agentskills.io/home) | Phần giới thiệu skill và hướng dẫn theo ngữ cảnh. | R08 ánh xạ hướng dẫn chuyên môn vào sáu vai trò trong P01. |
| 16 | [Agent Skills. Specification](https://agentskills.io/specification) | Directory structure, SKILL.md format và frontmatter. | Đối chiếu name, description, metadata và tệp tài nguyên. Hash theo run là quyết định trong đề tài. |
| 17 | [FastAPI. Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) | Caveat trong hướng dẫn tác vụ nền. | P01 tách tiến trình worker cho các run dài và bền qua lần khởi động API. |
| 18 | [SQLite. Appropriate Uses For SQLite](https://www.sqlite.org/whentouse.html) | When to choose a client/server database, Many concurrent writers. | Căn cứ xem xét tải ghi đồng thời khi đánh giá phạm vi một worker trong R09. |
| 19 | [LangChain. LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | Mục mô tả durable execution, human-in-the-loop. | Phương án tham chiếu khi giải thích lựa chọn state machine Python đã duyệt tại P01. |
| 20 | [Pydantic. Models](https://docs.pydantic.dev/latest/concepts/models/) | Phần Basic model usage và model validation. | D07 dùng schema để kiểm tra dữ liệu, sau đó kiểm tra nghiệp vụ như phiên bản artifact hay chu trình DAG. |
| 21 | [pytest. Managing pytest’s output](https://docs.pytest.org/en/stable/how-to/output.html#creating-junitxml-format-files) | Creating JUnitXML format files. | I15 cần lưu số ca chạy, lỗi, bỏ qua và commit kèm runner report cho mỗi lượt test. |

## Đối chiếu với sản phẩm và quyết định

| Mục | Căn cứ | Cách sử dụng |
| --- | --- | --- |
| P01 | [Đề cương đã duyệt](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/8c2fe7180ff08650b1488fe7d169ad9430427b73/P01/de_cuong_P01.md) và [bình luận của chủ dự án](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/2#issuecomment-7102034018) | Theo phạm vi, stack, số vai trò và câu hỏi nghiên cứu đã chốt. |
| R01 | [Báo cáo trên nhánh R01](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/32b2ce78a1ab602259899d77d0943c624fd226d2/R01/bao_cao_R01.md) và [bình luận đầu vào](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/3#issuecomment-7104514172) | Tra bình luận, nội dung báo cáo và lịch sử rà soát ở [sổ cái](../R10/so_cai_hoan_thanh.md). |
| R02 | [Báo cáo trên nhánh R02](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/4df0cc2b42654875b04974c7383e4a5be2fb6843/R02/bao_cao_R02.md) và [bình luận đầu vào](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/4#issuecomment-7109633981) | Tra bình luận, nội dung báo cáo và lịch sử rà soát ở [sổ cái](../R10/so_cai_hoan_thanh.md). |
| R03 | [Báo cáo trên nhánh R03](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/07148516d90f66ba6ddefe448c5a264bf5061a95/R03/bao_cao_R03.md) và [bình luận đầu vào](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/5#issuecomment-7167269005) | Tra bình luận, nội dung báo cáo và lịch sử rà soát ở [sổ cái](../R10/so_cai_hoan_thanh.md). |
| R04 | [Báo cáo trên nhánh R04](https://github.com/DaoNgocDinh/ChuyenDeKTPM/blob/01b0df2721f5b5ed38f9ac37abbfb1d8a546fe18/R04/bao_cao_R04.md) và [bình luận đầu vào](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/6#issuecomment-7167728123) | Tra bình luận, nội dung báo cáo và lịch sử rà soát ở [sổ cái](../R10/so_cai_hoan_thanh.md). |
| R05 | [Quyết định bỏ khỏi đề tài](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/7#issuecomment-7170813166) | Giữ số tham khảo gốc để truy nguyên phạm vi. |
| R06 | [Issue đã đóng](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/8) | Tại thời điểm kiểm tra, issue chưa có bình luận kèm báo cáo. Kiểm thử thật của ba bài thử sẽ được đối chiếu tại [E01](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/51). |

Các nguồn 1–6 là công trình học thuật. Nguồn 7–9 cung cấp cách tổ chức và ví dụ từ nhóm phát triển. Nguồn 10–21 mô tả hành vi giao thức, thư viện và công cụ. Kết luận về chất lượng sáu agent, tác dụng của skill và độ trễ MCP cần dữ liệu của E05–E08 và V02.

## Nhật ký hỗ trợ AI

| Ngày | Người thực hiện | Đầu vào và thao tác | Bằng chứng và phần còn mở |
| --- | --- | --- |
| 26/11/2026 | Codex | Trích 21 hyperlink của mục 7 trong Word gốc, mở từng nguồn, đối chiếu P01 và lịch sử R01–R06, lập chỉ mục để viết báo cáo. | Bảng trên và các commit liên kết. Chủ dự án bổ sung ngày tự đọc, nhận xét cá nhân, chuẩn trích dẫn và quy định AI của trường khi có. |

Nhật ký các buổi trước và ghi nhận của Anti nằm trong [sổ cái R10](../R10/so_cai_hoan_thanh.md). Khi bổ sung một buổi, ghi người thực hiện, ngày, đầu vào, sản phẩm, phép kiểm tra và phần còn chờ quyết định. Gắn nghiệm thu vào đúng phiên bản tài liệu hoặc commit.

## Kiểm tra

Chạy `python -m unittest tests.test_r10_sources` tại gốc nhánh `R10`. Nếu có bản Word chuẩn, chạy `python tests/test_r10_sources.py duong-dan-den-ban-goc.docx` để so cả 21 URL theo đúng thứ tự và SHA256.
