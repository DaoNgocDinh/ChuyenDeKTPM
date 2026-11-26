---
name: architecture-design
description: Chuyển bộ yêu cầu đã duyệt thành thiết kế cho ứng dụng CRUD.
metadata:
  version: "1.0"
---

1. Kiểm tra run, version/hash và quyết định duyệt requirements. Gặp mâu thuẫn ảnh hưởng thiết kế thì trả câu hỏi tới Requirement.
2. Lập ADR, component, thực thể và ràng buộc, endpoint, bố cục UI và chiến lược test. Gắn từng FR vào thành phần cụ thể.
3. Trả architecture có phiên bản cho Planning. Khi sửa, chỉ rõ các task và artifact chịu ảnh hưởng để host yêu cầu duyệt lại.
