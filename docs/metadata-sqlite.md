# I02 · Lưu metadata

API và worker cùng mở `Database(path)` trong [backend/storage.py](../backend/storage.py). Lúc khởi động gọi `migrate()`. Mỗi transaction dùng một connection mới có khóa ngoại, ghi bằng `BEGIN IMMEDIATE` và rollback khi có ngoại lệ. Migration kiểm tra phiên bản sau khi lấy khóa để hai tiến trình có thể khởi động cùng lúc.

```python
from backend.storage import Database

database = Database("workspaces/platform.sqlite")
database.migrate()
with database.transaction(write=True) as repo:
    project_id = repo.create_project("A1", "brief/A1")
    run_id = repo.create_run(project_id, "gui-lan-1", {"model": "fixture"}, {"tokens": 500})
with database.transaction() as repo:
    state = repo.get_run(project_id, run_id)
    events = repo.for_run(project_id, run_id).events_after(0)
```

Gửi lại cùng khóa idempotency và đầu vào trả về cùng run. Khóa dùng lại với cấu hình khác trả lỗi `StorageConflict`. Host ghi quyết định với `record_approval`, tham chiếu đúng phiên bản hiện hành và hash. Để ghi bước, artifact, task, dependency, tool call, report, trace hoặc event, worker phải lấy `repo.worker_run(project_id, run_id, lease)` bên trong một transaction ghi. Mỗi thao tác dùng lại lease phải được kiểm lại ở transaction tiếp theo. Worker chỉ gửi JSON đã lọc secret. Các tham chiếu FR nằm trong nội dung artifact được xác minh ở tầng truy vết.

**Cách test** · Chạy `python -m unittest -v tests.test_storage tests.test_platform_schema`. Mong đợi 15 ca đạt, gồm mở lại DB bằng tiến trình Python mới, tám lần gửi job đồng thời, rollback và các ca bị chặn do sai project, lease, hash hoặc FK.
