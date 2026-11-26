# Đề xuất nâng cấp nội dung 6 `SKILL.md` (Bản hỗ trợ — Chưa áp dụng chính thức)

> **Trạng thái:** Đây là **bản gợi ý hỗ trợ (draft `0.2.0-draft`)** giúp giảm độ nặng khi triển khai 6 agent thật (`I06`, `I09–I11`, `I16–I17`), **không ghi đè** các tệp đang khóa trong `skills/*/SKILL.md` của nhánh `I08`. Chủ dự án rà soát, chỉnh sửa theo ý muốn và chỉ thay thế vào `skills/` khi đồng ý (và khóa hash trước `E04`).

## Danh mục 6 bản đề xuất

| Vai trò | Thư mục đề xuất | Căn cứ hợp đồng đã đối chiếu |
| --- | --- | --- |
| `Orchestrator` | `docs/de-xuat-skills/workflow-coordination/SKILL.md` | `P01`, `D05`, `D06`, `D08`, `D11` |
| `Requirement` | `docs/de-xuat-skills/requirements-analysis/SKILL.md` | `P01`, `D01`, `D05`, `D07`, `D11` |
| `Architecture` | `docs/de-xuat-skills/architecture-design/SKILL.md` | `P01`, `D05`, `D07`, `D11` |
| `Planning` | `docs/de-xuat-skills/task-planning/SKILL.md` | `P01`, `D05`, `D07`, `D11` |
| `Dev` | `docs/de-xuat-skills/implementation/SKILL.md` | `P01`, `D05`, `D07`, `D11`, `I12` |
| `Tester` | `docs/de-xuat-skills/testing-review/SKILL.md` | `P01`, `D05`, `D07`, `D11`, `I15` |

## Kiểm tra bản đề xuất

```sh
uv run --no-project --with PyYAML python -m unittest tests.test_registry tests.test_skill tests.test_skill_drafts -v
```

Bộ kiểm tra xác minh cả 6 tệp đề xuất đều vượt qua `backend.skills.load_skill(...)` của `I08` và 6 tệp gốc trong `skills/` giữ nguyên không bị thay đổi.
