# D11 · Quyền công cụ và cô lập runner

Bản đề xuất cho I13–I15. P01 và D05 xác định các vùng ghi của sáu vai trò. Chủ dự án chọn Docker, cho phép tải công cụ cần thiết và cho phép kết nối Internet chiều ra trong lúc test. Container dùng mạng bridge riêng của Docker. Chính sách cấm chia sẻ namespace mạng của host, truyền credential hoặc mount Docker socket. Giới hạn khởi đầu đã duyệt cho mỗi lượt là 2 CPU, 2 GiB RAM, 128 PID, 180 giây và tối đa 1 MiB log. [Hợp đồng vai trò](hop-dong-vai-tro.md) · [Ma trận quyền có thể kiểm tra](quyen-cong-cu.json)

### Ranh giới thực thi

1. **Host** lấy project, run, step, role, task và phiên bản mã từ trạng thái đã lưu. Xác minh lease, trạng thái, quota và phiên bản đầu vào trước khi chuyển yêu cầu. Model chỉ đề xuất tên tool và đối số nghiệp vụ. Từ chối thuộc tính ngoài schema, kể cả trường tự khai role/run. Mỗi subprocess hoặc phiên MCP được ràng buộc vào context của một bước. Khi bước kết thúc, host hủy phiên.
2. **Gateway và MCP server** dùng cùng policy, từ chối mặc định khi thiếu quyền. Server lặp lại kiểm tra trên đối tượng thật, đường dẫn và context do host cấp. Artifact chỉ đọc qua ID + version dưới đúng project/run, sau kiểm tra quyền trên loại artifact. Nội dung mã, log, prompt và skill đều là dữ liệu, không cấp quyền hoặc làm căn cứ để sửa policy.
3. **Docker và runner** nhận suite ID do Gateway đã kiểm tra. Host chọn profile, gửi đúng file của commit cần chạy. Container không nhận credential LLM, socket daemon, thư mục người dùng, `.git`, thư mục policy/skill hay evaluation dùng cho bộ nghiệm thu. Khi chạy nghiệm thu độc lập, một harness riêng cấp test ở chế độ chỉ đọc trong môi trường do người đánh giá quản lý. Không trả nội dung test độc lập cho agent qua log hoặc artifact.

### Ma trận kiểm tra theo vai trò

| Vai trò | Ca cho phép | Ca từ chối, trước tác dụng phụ |
| --- | --- | --- |
| Orchestrator | Đọc artifact của run hiện hành và đề xuất chuyển bước để host kiểm tra | Gọi apply patch lên app hoặc tự ghi người duyệt |
| Requirement | Đọc brief qua host, phát hành requirements mới qua artifact store | Sửa đè phiên bản đã được duyệt, gọi Git hoặc đọc artifact của run khác |
| Architecture | Đọc requirements đã duyệt, gửi thiết kế mới cho host lưu | Thay brief, tự mở cổng duyệt hoặc chạy suite |
| Planning | Đọc cặp yêu cầu/thiết kế, gửi DAG cho host kiểm tra | Dùng tool ghi mã hoặc chỉnh kiến trúc nguồn |
| Dev | Đọc mã được giao, áp patch trong `app/` với đúng task, expected hash và commit, gọi suite được cấp | Ghi vào `tests_dev/`, truy cập policy, bộ nghiệm thu hoặc gửi lệnh shell |
| Tester | Đọc diff của commit được giao, ghi test ở `tests_dev/`, chạy suite phát triển, gửi nhận xét và bug cho host | Ghi `app/`, nhận test nghiệm thu độc lập hoặc báo pass khi runner chưa chạy |

Hai vai trò cuối được đọc tệp thường nằm trong các root được liệt kê. Tool status/diff chỉ trình bày thay đổi được phép đọc ở commit của run và phải lọc tệp ẩn, credential cùng kết quả nhạy cảm trước khi trả. Công cụ ghi cần tách đường dẫn đích cũ/mới của từng hunk, kiểm toàn bộ bản vá, kiểm hash và ghi nguyên tử. Host giữ quyền tạo Git checkpoint. Mọi vai trò bị chặn truy cập tệp ngoài workspace của run và cơ sở dữ liệu nền tảng qua tool.

### Threat model và phép thử

| Tình huống | Cơ chế kiểm tra | Bằng chứng cần thu từ I13–I15/V02 |
| --- | --- | --- |
| Host nhận yêu cầu sai vai trò, khác run hoặc từ bước đã hết lease | Kiểm context đáng tin, schema đối số, ownership và quan hệ task/step tại thời điểm gọi | Bản ghi từ chối có run/step, không thấy thay đổi ở run đích |
| Đường dẫn ra khỏi vùng cấp quyền | Chỉ cho đường dẫn tương đối trong root đã mở. Từ chối ổ đĩa/UNC, đường dẫn tuyệt đối, symlink/reparse point ra ngoài, đổi đích trong lúc thao tác. Khi hệ thống không thể kiểm soát được đích cuối, từ chối ghi | Fixture có file hợp lệ và liên kết dẫn ra ngoài. Chỉ file hợp lệ được đọc hoặc ghi |
| Nội dung repo hoặc kết quả tool yêu cầu nâng quyền | Tách dữ liệu trả về khỏi trường điều khiển, đặt giới hạn kích thước và cắt ngắn dữ liệu. Model đề xuất lệnh mới vẫn qua Gateway như thường | Chèn một chỉ dẫn vô hại trong fixture, xác nhận allowlist, quyền và mục tiêu thực tế giữ nguyên |
| Rò credential qua log hoặc file xuất | Adapter giữ key ngoài ngữ cảnh model và runner. Dùng allowlist trường log, che trường nhạy cảm đệ quy và làm sạch chuỗi trước khi lưu/hiển thị. Áp dụng cho thành công, từ chối, lỗi parse, exception và output runner | Dùng giá trị giả kiểu canary rồi kiểm tra event, stderr, report, artifact và ZIP, gồm cả nhánh lỗi |
| Suite chạy quá giới hạn hoặc bỏ sót tiến trình con | Profile khóa argv, cwd, image theo digest và các mức tài nguyên. Docker chạy user không đặc quyền, rootfs chỉ đọc, thư mục scratch riêng theo lượt. Khi timeout/cancel, dừng container và thu trạng thái cuối | Run sau bắt đầu SDK/runner sạch, không còn container con hoặc tiến trình của lượt trước |
| Dữ liệu báo cáo không khớp bản mã | Host ghim commit và suite trước khi chạy, đọc JUnit/JSON ở thư mục output riêng, kiểm tổng số ca và exit code | Report có commit, số pass/fail/error/skip, thời lượng và trạng thái. Suite rỗng hoặc không thu được report có lý do thất bại |

### Hợp đồng runner profile

Profile do host quản lý gồm suite ID, digest image, executable, danh sách đối số cố định, cwd, network policy, timeout, CPU, memory, số PID và giới hạn output. Lệnh được khởi chạy bằng mảng đối số. Không ghép shell hay chuyển chuỗi command, đối số, image hoặc đường dẫn mount do model tạo thành lệnh Docker. Khi thiếu policy mạng hoặc giới hạn bắt buộc, profile chưa sẵn sàng. `materialized_profiles` hiện để trống vì D11 đặc tả hợp đồng, bằng chứng chạy suite thật thuộc I15.

Khâu chuẩn bị dependency tải thành phần cần thiết và khóa phiên bản trước khi xây image. Khi test, Docker dùng mạng bridge với kết nối chiều ra. Không publish cổng, dùng host network hoặc chạy chế độ đặc quyền. Do mã được test có quyền ra Internet, host chỉ đưa fixture, bản sao mã theo commit và dữ liệu được phép vào container. Trường `resource_limits` trong ma trận quyền ghi giá trị đã duyệt, theo byte và giây. [Runner profile](../backend/runner_profile.py) chỉ nhận cấu hình do host quản lý và kiểm tra ngay khi nạp.

**Cách test.** Chạy `python -m unittest tests.test_tool_policy_contract` để đối chiếu sáu vai trò, vùng ghi, giới hạn profile và quyền truy cập evaluation. Khi có Gateway và runner, dùng từng ca trong hai bảng để kiểm tra tác dụng phụ và lấy log thực thi.
