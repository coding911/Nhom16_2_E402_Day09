# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Lại Đức Anh  
**Vai trò trong nhóm:** MCP Owner / Worker Owner  
**Ngày nộp:** 14/04/2026  

---

## 1. Tôi phụ trách phần nào? 

**Module/file tôi chịu trách nhiệm:**
- File chính: `mcp_server.py`, `workers/policy_tool.py`
- Functions tôi implement: `_call_mcp_tool()`, `tool_search_kb()`, `tool_get_ticket_info()`, `tool_check_access_permission()`, `run()`

Tôi chịu trách nhiệm phần MCP mock server và worker policy logic. Tôi viết `mcp_server.py` để mô phỏng MCP tool discovery và dispatch, đồng thời tích hợp các tool call vào `workers/policy_tool.py`. Tôi đảm bảo worker ghi lại `mcp_tools_used` và `mcp_access_result` trong state, giúp trace hiện đầy đủ các tool được gọi.

**Cách công việc của tôi kết nối với phần của thành viên khác:**

Khi Minh Tri xác định supervisor route `policy_tool_worker`, tôi đảm bảo `policy_tool.py` có thể xử lý chính sách và gọi MCP tools đúng với route đó. Kết quả từ tôi được `synthesis_worker` dùng để xây câu trả lời; Thạch dùng trace output để đánh giá toàn bộ pipeline.

**Bằng chứng (commit hash, file có comment tên bạn, v.v.):**

`mcp_server.py` chứa định nghĩa tool schema và implementation `dispatch_tool()` cho `search_kb`, `get_ticket_info`, `check_access_permission`. `workers/policy_tool.py` gọi `_call_mcp_tool()` khi `needs_tool=True`.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? 

**Quyết định:** Tôi chọn dùng in-process MCP dispatch thay vì triển khai HTTP server trong lab.

Tôi cân nhắc giữa hai hướng: triển khai FastAPI/HTTP để giả lập MCP thực thụ, hoặc dùng import trực tiếp `dispatch_tool()` trong cùng process. Tôi chọn phương án import trực tiếp vì thời gian giới hạn và vì điều đó dễ debug hơn trong môi trường lab.

**Lý do:**

- Đảm bảo MCP tool calls hoạt động ngay khi chạy `python graph.py` mà không cần khởi động server riêng.
- Giảm complexity môi trường và tránh lỗi network hoặc CORS.
- Vẫn giữ được ý nghĩa phân tách tool contract vì `mcp_server.py` vẫn định nghĩa `TOOL_SCHEMAS` và `dispatch_tool()`.

**Trade-off đã chấp nhận:**

Tôi chấp nhận mất điểm bonus nếu nhóm cần http-based MCP, nhưng đổi lại chúng tôi có một cơ chế MCP ổn định và traceable trong lab.

**Bằng chứng từ trace/code:**

```
# workers/policy_tool.py
from mcp_server import dispatch_tool
...
mcp_result = _call_mcp_tool("check_access_permission", {...})
state["mcp_tools_used"].append(mcp_result)
```

Trace gq09 ghi `mcp_tools_used`: ["check_access_permission", "get_ticket_info"].

---

## 3. Tôi đã sửa một lỗi gì? 

**Lỗi:** `policy_tool.py` ban đầu không đảm bảo `state["mcp_tools_used"]` luôn tồn tại và có thể bỏ qua log MCP calls.

**Symptom (pipeline làm gì sai?):**

Khi `policy_tool_worker` gọi MCP, trace không ghi `mcp_tools_used`, nên nhóm không biết tool nào đã thực sự được dùng. Điều này gây khó khăn khi xác định gq09 có sử dụng `check_access_permission` hay không.

**Root cause (lỗi nằm ở đâu — indexing, routing, contract, worker logic?):**

Lỗi nằm trong worker logic của `workers/policy_tool.py`: state chưa được khởi tạo đầy đủ trước khi append tool call.

**Cách sửa:**

Tôi thêm `state.setdefault("mcp_tools_used", [])` và đảm bảo mỗi lần `_call_mcp_tool()` trả về kết quả thì `state["mcp_tools_used"].append(mcp_result)` được thực hiện. Tôi cũng sửa `worker_io` để ghi output `mcp_tools_called`.

**Bằng chứng trước/sau:**

Trước: `mcp_tools_used` có thể không tồn tại trong trace.  
Sau: gq09 trace có `mcp_tools_used` rõ ràng và `history` ghi `called MCP check_access_permission`.

---

## 4. Tôi tự đánh giá đóng góp của mình 

**Tôi làm tốt nhất ở điểm nào?**

Tôi làm tốt nhất ở việc kết nối MCP tool contract và worker policy logic. Tôi giữ được đường dẫn tool calls rõ ràng và đảm bảo `policy_tool_worker` có dữ liệu để đưa vào `synthesis_worker`.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Tôi chưa hoàn thiện phần HTTP MCP server và chưa đưa `create_ticket` vào đường flow thực tế. Tôi cũng có thể cải thiện cách ghi lỗi `mcp_tool` để cảnh báo khi tool call fail.

**Nhóm phụ thuộc vào tôi ở đâu?** _(Phần nào của hệ thống bị block nếu tôi chưa xong?)_

Nhóm phụ thuộc vào tôi cho phần policy/access và tất cả câu hỏi cần MCP tool. Nếu tôi chưa xong, gq03 và gq09 sẽ thiếu tool call, và trace không còn đủ thông tin để chứng minh multi-agent hoạt động.

**Phần tôi phụ thuộc vào thành viên khác:** _(Tôi cần gì từ ai để tiếp tục được?)_

Tôi phụ thuộc vào Minh Tri để định nghĩa trạng thái và route logic đúng, và Thạch để xác minh rằng trace tôi tạo ra đủ chi tiết cho grading.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? 

Tôi sẽ hoàn thành HTTP mock MCP service và chuyển `dispatch_tool()` sang một client/server interface. Trace gq09 cho thấy MCP tool calls quan trọng với policy/access, nên tôi muốn nâng cấp từ import trực tiếp sang HTTP để mô phỏng MCP thực tế và cho phép tách worker khỏi server process.

---

