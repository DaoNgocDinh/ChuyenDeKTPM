# D01 · Nghiệm thu nền tảng sáu vai trò

**Chủ dự án đã duyệt phạm vi D01 trong chat ngày 26/11/2026.** Quyết định áp dụng cho sáu luồng và 18 yêu cầu của [bản đã trình duyệt](https://github.com/DaoNgocDinh/ChuyenDeKTPM/commit/30cb6f389c02139523357fbbb9c9b2801e2a018c). Người duyệt bằng chứng khi nghiệm thu hệ thống là chủ dự án. Nguồn là bản Word ngày 17/11/2026, mục 3.1–3.3, và [đề cương P01](ke-hoach.md). SHA256 bản Word là `975228EA14EDCE90CFECBBFE05C9911DD33B35FD1A4ACEF75577A9499D884C9F`.

## Người dùng và luồng thao tác

Người dùng nhập đề bài, làm rõ, duyệt các phiên bản trung gian, theo dõi tiến độ và nghiệm thu đầu ra. Nhà cung cấp LLM và MCP server là hai hệ thống bên ngoài. Orchestrator, Requirement, Architecture, Planning, Dev và Tester là sáu vai trò bên trong. FR/NFR bên dưới áp dụng cho **nền tảng**. Yêu cầu của ứng dụng A1, A2 hoặc A3 là đầu vào riêng của mỗi project.

| Luồng | Người dùng thao tác | Nền tảng phản hồi và bằng chứng cần xem |
| --- | --- | --- |
| Tạo và khởi chạy | Nhập mô tả, ràng buộc, tạo project rồi bắt đầu run. | Lưu đầu vào và xếp run vào hàng đợi. Khi tới lượt, worker nhận run. Có thể tìm lại bằng project ID và run ID. |
| Làm rõ và duyệt yêu cầu | Trả lời câu hỏi của Requirement, đọc SRS, duyệt hoặc yêu cầu sửa. | Ghi câu trả lời và xuất requirements có phiên bản. Cổng 1 chờ quyết định của người dùng cho đúng phiên bản trước khi chuyển qua thiết kế. |
| Duyệt thiết kế và kế hoạch | Xem ADR, DB, API và DAG, duyệt hoặc yêu cầu sửa. | Cổng 2 giữ Dev ở trạng thái chờ cho tới khi cả thiết kế và kế hoạch hiện hành được duyệt. Lưu quyết định và phiên bản. |
| Phát triển và sửa lỗi | Theo dõi task, patch, kết quả test và log. | Dev bàn giao patch. Tester viết test, review và chạy suite. Lỗi mã quay về Dev để sửa rồi kiểm tra lại. Lỗi yêu cầu hoặc thiết kế quay về đúng vai trò và chờ duyệt phiên bản thay đổi trước khi tiếp tục. |
| Dừng, lỗi và khôi phục | Xem lý do dừng hoặc yêu cầu dừng. Kiểm tra checkpoint trước khi tiếp tục. | Khi tool lỗi hoặc hết quota, lưu sự kiện, lý do và hành động kế tiếp. Sau restart, giữ artifact đã xong và đưa bước chưa rõ kết quả vào `pending_recovery` để tránh tác động lặp. |
| Kết thúc | Xem kết quả, tải bản xuất, chấp nhận đầu ra hoặc nêu phần cần sửa. | Hiển thị code, diff, test report và truy vết. Người dùng có thể đối chiếu ZIP với phiên bản được kiểm tra và ghi quyết định nghiệm thu. |

## Ma trận kiểm tra

Mỗi dòng mô tả thao tác cần thực hiện khi có bản chạy và bằng chứng phải thu. Chỉ ghi kết quả đạt sau khi chủ dự án kiểm tra các bằng chứng trên run cụ thể.

| Mã | Yêu cầu và cách thử | Bằng chứng mong đợi |
| --- | --- | --- |
| FR01 | Tạo project với mô tả và ràng buộc, sau đó mở lại. | Có project ID, đọc lại được mô tả và ràng buộc ban đầu. |
| FR02 | Gửi đề bài thiếu thông tin, trả lời câu hỏi rồi xem SRS. | requirements.json hợp schema, có tác nhân, FR, NFR, giả định, câu hỏi và tiêu chí chấp nhận. |
| FR03 | Thử đi tiếp khi chưa duyệt, yêu cầu sửa rồi duyệt đúng phiên bản tại cả hai cổng. | Workflow dừng đúng cổng. Lịch sử giữ quyết định sửa/duyệt và phiên bản tương ứng. Quyết định cho bản cũ không mở cổng cho bản mới. |
| FR04 | Duyệt yêu cầu rồi mở đầu ra của Architecture và Planning. | Có ADR, schema DB, API contract và các task cùng quan hệ phụ thuộc tạo thành DAG. |
| FR05 | Giao một task cho Dev rồi xem thay đổi trong workspace của run. | Patch/diff ghi đúng file và nhận diện được phiên bản mã bằng Git checkpoint hoặc hash. |
| FR06 | Cho Tester kiểm tra một phiên bản có lỗi tái hiện được. | Có test phát triển, nhận xét review, báo cáo runner thật và bug report mô tả cách tái hiện. |
| FR07 | Tạo lỗi mã, lỗi thiết kế và lỗi yêu cầu. Cho một task tiếp tục lỗi sau ba vòng sửa. | Log chuyển về đúng vai trò cho từng lỗi. Task dừng và ghi lý do trước khi chạy vòng sửa thứ tư. |
| FR08 | Kiểm tra skill của từng vai trò, chạy một tool hợp lệ và một yêu cầu ngoài quyền. | Có hash skill, log gọi tool qua MCP và bản ghi từ chối theo vai trò. |
| FR09 | Chọn một FR của ứng dụng rồi tìm task, patch và kết quả test cùng run. | Các bản ghi sự kiện và liên kết tham chiếu đúng phiên bản artifact theo chuỗi FR → task → patch → test. |
| FR10 | Dừng run, khởi động lại worker, xem trạng thái, khôi phục khi đủ điều kiện và tải bản xuất của run đã xong. | Trạng thái được đọc lại. ZIP mở được và có mã, README, tài liệu và test report đúng run. |
| NFR01 | Khởi chạy hai run trong khi worker đang xử lý run thứ nhất. | Có một run hoạt động, run thứ hai ở queued và hai workspace tách biệt. |
| NFR02 | Dừng worker giữa một thao tác chưa rõ đã hoàn tất rồi bật lại. | Tìm lại được checkpoint cùng artifact cũ. Run đi vào pending_recovery khi kết quả thao tác chưa xác định. |
| NFR03 | Lần lượt đặt trần token, thời gian, tool call thấp và cho một task sửa lỗi lặp. | Mỗi lần dừng có lý do khớp trần tương ứng. Mỗi task có tối đa ba vòng sửa sau lần triển khai đầu. |
| NFR04 | Kiểm tra Tester yêu cầu sửa app, Dev yêu cầu sửa bộ nghiệm thu và một đường dẫn nằm ngoài workspace. | Tầng thực thi chặn theo vai trò/phạm vi run. File đích giữ nguyên, log lưu lý do. |
| NFR05 | Chọn một run rồi đối chiếu các đầu vào cần cho lần chạy lại. | Có model, hash prompt/skill, lockfile, schema tool, đầu vào và phiên bản mã. |
| NFR06 | Dùng một chuỗi giả làm API key trong môi trường kiểm thử, rà repo, prompt, artifact, log và ZIP. | Chuỗi mẫu không xuất hiện trong các đầu ra. Kiểm tra được cả nhánh thành công và lỗi. |
| NFR07 | Lấy một test report, mở kết quả gốc từ runner và đối chiếu. | Khớp exit code, kết quả JUnit XML hoặc JSON, thời gian chạy và commit mã đã chạy. |
| NFR08 | Mở giao diện khi đang chạy, khi chờ duyệt và khi có lỗi. | Nhìn thấy bước hiện tại, artifact cần duyệt, lý do dừng và hành động kế tiếp phù hợp. |

## Kiểm tra nhánh

Chạy `git grep -En "^\| (FR|NFR)[0-9]{2} " -- docs/nghiem-thu-nen-tang.md`. Đối chiếu 18 dòng liên tiếp FR01–FR10, NFR01–NFR08 với hai bảng ở mục 3.2 và 3.3 bản Word. Kiểm tra hai cổng, luồng sửa và khôi phục trong bảng luồng. Bằng chứng chạy hệ thống sẽ được bổ sung tại V01 và V02.

Theo dõi bằng chứng thực thi và các đề xuất thay đổi phạm vi qua [issue D01](https://github.com/DaoNgocDinh/ChuyenDeKTPM/issues/13).
