# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Nguyễn Minh Trí  
**Vai trò trong nhóm:** Graph Owner  
**Ngày nộp:** 14/04/2026  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào? 

**Module/file tôi chịu trách nhiệm:**
- File chính: `graph.py`
- Functions tôi implement: `make_initial_state()`, `supervisor_node()`, `route_after_supervisor()`, `route_after_retrieval()`, `route_after_judge()`, `human_review_node()`

Tôi chịu trách nhiệm thiết kế luồng supervisor-worker và giao tiếp giữa state chung. Tôi định nghĩa cách task được phân loại bằng keyword routing, cách `policy_tool_worker` vẫn phải đi qua `retrieval_worker` trước, và cách `judge_worker` quyết định retry hoặc kết thúc. Tôi cũng xây dựng state schema `AgentState` để theo dõi trace và `workers_called`.

**Cách công việc của tôi kết nối với phần của thành viên khác:**

Khi Đức Anh viết `policy_tool.py`, tôi phải đảm bảo `graph.py` cung cấp đúng `needs_tool` và `supervisor_route`. Khi Thạch chạy grading và trace, tôi phải cung cấp route_reason rõ ràng để họ có thể phân tích gq09 và gq03.

**Bằng chứng (commit hash, file có comment tên bạn, v.v.):**

`graph.py` có phần `supervisor_node()` với keyword lists `policy_keywords`, `retrieval_keywords`, và `risk_keywords`. `route_after_retrieval()` đảm bảo route `policy_tool_worker` chỉ xảy ra sau retrieval.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì? 

**Quyết định:** Tôi chọn dùng rule-based keyword routing trong `supervisor_node()` và duy trì `retrieval-first` cho policy path.

Lựa chọn thay thế là dùng LLM để classify task, hoặc trực tiếp route `policy_tool_worker` mà không qua retrieval. Tôi chọn keyword rules vì dữ liệu lab có các pattern rõ như `level 2`, `flash sale`, `ticket`, `p1`.

**Lý do:**

- Rule-based routing giúp trace rõ `route_reason` và debug nhanh.
- Keyword routing tiết kiệm latency so với classifier LLM.
- Retrieval-first giảm nguy cơ `policy_tool_worker` xử lý mà không có evidence.

**Trade-off đã chấp nhận:**

Tôi chấp nhận việc mở rộng domain sau này sẽ cần cập nhật `policy_keywords`/`retrieval_keywords`, nhưng đổi lại chúng tôi có một cơ chế đơn giản, ổn định và dễ hiểu.

**Bằng chứng từ trace/code:**

```
# graph.py
if matched_policy:
    route = "policy_tool_worker"
    route_reason = f"policy/access keywords detected: {matched_policy} → MCP tools will be invoked"
...
if route == "policy_tool_worker" and not hitl:
    return "policy_tool_worker"
```

Trace gq09 phản ánh đúng logic đó và `workers_called` cho thấy multi-hop retrieval → policy → synthesis.

---

## 3. Tôi đã sửa một lỗi gì? 

**Lỗi:** ban đầu `policy_tool_worker` có thể được gọi mà không có chunks nếu route không đi qua `retrieval_worker`.

**Symptom (pipeline làm gì sai?):**

Khi `supervisor_route` là `policy_tool_worker`, `policy_tool.py` vẫn cần evidence để phân tích policy. Nếu không có retrieval trước, worker có thể chỉ dựa vào task và tạo ra output thiếu căn cứ.

**Root cause (lỗi nằm ở đâu — indexing, routing, contract, worker logic?):**

Lỗi nằm ở edge routing trong `graph.py`, chính xác là trong `route_after_supervisor()` và `route_after_retrieval()`.

**Cách sửa:**

Tôi sửa `route_after_supervisor()` để luôn trả về `retrieval_worker` khi route là `policy_tool_worker`, và `route_after_retrieval()` để sau retrieval nối tiếp sang `policy_tool_worker` nếu `supervisor_route` ban đầu là policy. Điều này giữ nguyên `retrieved_chunks` trước khi chính sách được đánh giá.

**Bằng chứng trước/sau:**

Sau sửa, trace gq03/gq09 đều có `workers_called` bắt đầu bằng `retrieval_worker`. Điều này giúp `policy_tool_worker` có `retrieved_chunks` và `policy_result` chính xác.

---

## 4. Tôi tự đánh giá đóng góp của mình 

**Tôi làm tốt nhất ở điểm nào?**

Tôi làm tốt nhất ở thiết kế luồng và state schema. `graph.py` đóng vai trò trung tâm để kết nối supervisor, worker và judge, và tôi đã giữ cho trace dễ đọc.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

Tôi chưa tự động hóa được phần route testing và vẫn dùng nhiều kiểm tra thủ công. Tôi cũng có thể cải tiến phần `risk_keywords` để giảm false positive.

**Nhóm phụ thuộc vào tôi ở đâu?** _(Phần nào của hệ thống bị block nếu tôi chưa xong?)_

Nhóm phụ thuộc vào tôi cho workflow chính: nếu `graph.py` còn lỗi, toàn bộ pipeline có thể route sai hoặc không giữ đúng state giữa worker.

**Phần tôi phụ thuộc vào thành viên khác:** _(Tôi cần gì từ ai để tiếp tục được?)_

Tôi phụ thuộc vào Đức Anh cho logic MCP và policy, và Thạch cho phần grading/trace để xác nhận đường flow tôi tạo ra thật sự có hiệu quả.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì? 

Tôi sẽ bổ sung một lớp supervisor LLM fallback cho những câu không khớp keyword rõ, vì trace gq03/gq09 cho thấy keyword routing hiện tại hoạt động nhưng có thể mất chính xác khi mở rộng câu hỏi mới. Một fallback LLM classifier sẽ giúp giảm false negative routing mà không thay đổi cấu trúc worker hiện tại.

---
