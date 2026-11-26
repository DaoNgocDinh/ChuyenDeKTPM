# I03 · Kho artifact

Host khởi tạo `ArtifactStore(workspace_root, database)` và gọi `put(project_id, run_id, lease, kind, content, created_by=role, expected_previous_version=n, parent_refs=refs)`. Giá trị 0 tạo phiên bản đầu. Hàm trả `ArtifactRef` của D07. `read(project_id, run_id, artifact_id, version, sha256)` trả đúng bytes đã lưu sau khi đối chiếu hash. Dịch vụ tự chọn đường dẫn từ project/run và hash.

Các loại JSON gồm requirements, architecture, plan, dev_result, test_report và bug_report. JSON được kiểm bằng schema D07 và ghi ở dạng UTF-8 nhất quán để tính hash. Tài liệu, Markdown, log, output của runner và patch dùng UTF-8. Host truyền các tham chiếu bàn giao qua parent_refs. Những tham chiếu ngay trong payload như nguồn requirements của architecture cũng được đối chiếu và lưu.

Host sở hữu thư mục artifacts. Runner chỉ được cấp workspace app và vùng test phù hợp. Kho dùng filesystem hỗ trợ hard link, ví dụ NTFS. File tạm được ghi trọn, đồng bộ và công bố bằng liên kết nguyên tử trước khi transaction ghi metadata. Nếu tiến trình chết giữa hai bước, blob chưa có metadata sẽ không được trả qua API và có thể tái sử dụng khi ghi lại cùng nội dung. Hai lần ghi cạnh tranh cùng phiên bản chỉ có một bản được công bố trong DB.

**Cách test** · Chạy `uv run --frozen python -m unittest tests.test_artifacts -v`. Mong đợi 5 test đạt, gồm hai phiên bản cùng tồn tại sau duyệt, sai scope/hash, schema lỗi, ghi trùng, lỗi đĩa và phát hiện file hỏng.
