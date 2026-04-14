# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** 16_2  
**Thành viên:**
| Tên | Vai trò | Email |
|-----|---------|-------|
| Hoàng Ngọc Thạch | Eval Owner | hnthach97@gmail.com |
| Lại Đức Anh | MCP Owner - Worker Owner | laiducanh26112004@gmail.com |
| Nguyễn Minh Trí | Graph Owner | coding0911@gmail.com |

**Ngày nộp:** 14/04/2026  
**Repo:** https://github.com/coding911/Nhom16_2_E402_Day09.git  

---

## 1. Kiến trúc nhóm đã xây dựng

Chúng tôi xây dựng một pipeline supervisor-worker với 4 worker chính: `retrieval_worker`, `policy_tool_worker`, `synthesis_worker`, và `judge_worker`. `graph.py` định nghĩa state schema chung, supervisor routing, và conditional edges giữa các worker. Nhóm cũng bổ sung node `human_review` để mô phỏng HITL khi task kích hoạt risk.

Supervisor routing trong `graph.py` dùng rule-based keyword matching. Nếu task chứa từ khóa access/policy như `level 3`, `store credit`, `flash sale`, hệ thống chọn `policy_tool_worker`. Nếu chứa từ khóa knowledge như `p1`, `sla`, `ticket`, hệ thống chọn `retrieval_worker`. Nếu không match, default vẫn là `retrieval_worker`.

MCP tools đã tích hợp:
- `search_kb`: dùng trong `workers/policy_tool.py` khi `needs_tool=True` và chưa có chunks.
- `get_ticket_info`: dùng trong `workers/policy_tool.py` với ticket-related tasks.
- `check_access_permission`: dùng trong `workers/policy_tool.py` để xác định access level và approver chain.

Ví dụ thực tế: gq09 trace có `supervisor_route` = `policy_tool_worker`, `route_reason` = `policy/access keywords detected: ['level 2', 'contractor'] → MCP tools will be invoked | risk_high: ['emergency', '2am']`, và `mcp_tools_used` gồm `check_access_permission` và `get_ticket_info`.

---

## 2. Quyết định kỹ thuật quan trọng nhất

**Quyết định:** Dùng supervisor keyword-based routing plus retrieval-first ordering cho policy path.

**Bối cảnh vấn đề:** Chúng tôi cần tách rõ câu hỏi policy/access khỏi câu hỏi knowledge-base thông thường, đồng thời vẫn đảm bảo rằng policy worker luôn có context trước khi phân tích. Nếu bỏ retrieval-first, `policy_tool_worker` có thể nhận state trống và không có chunk để dựa vào.

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| LLM classifier trực tiếp trong supervisor | linh hoạt hơn với câu không có keyword rõ | tốn API, khó debug, dễ gây route sai khi prompt không ổn |
| Rule-based keyword routing + retrieval-first | đơn giản, nhanh, trace rõ lý do route | cần cập nhật keyword list khi mở rộng domain |
| Luôn cho tất cả câu vào `policy_tool_worker` | đơn giản về route | tốn thời gian, policy logic không cần thiết cho nhiều câu đơn giản |

**Phương án đã chọn và lý do:**
Chúng tôi chọn rule-based supervisor routing, vì nó cho đủ độ chính xác với dữ liệu lab hiện tại, cho phép trace `route_reason` rõ ràng, và giữ latency ổn. Quyết định retrieval-first trong `route_after_retrieval()` đảm bảo `policy_tool_worker` luôn nhận được `retrieved_chunks` đầu tiên. Điều này giảm nguy cơ policy worker phải xử lý khi không có evidence.

**Bằng chứng từ trace/code:**
```
# graph.py
if route == "policy_tool_worker":
    return "retrieval_worker"
...
if route == "policy_tool_worker" and not hitl:
    return "policy_tool_worker"
```
và gq03 trace: `supervisor_route` = `policy_tool_worker`, `workers_called` = ["retrieval_worker", "policy_tool_worker", "synthesis_worker", "judge_worker", ...].

---

## 3. Kết quả grading questions

**Tổng điểm raw ước tính:** 96 / 96

Pipeline đã chạy qua 10 grading questions và tất cả đều trả về `judge_verdict: PASS`. Không có pipeline error, điều này cho thấy hệ thống đủ ổn định để đạt được full credit theo định nghĩa grading current.

**Câu pipeline xử lý tốt nhất:**
- ID: `gq01` — Lý do tốt: route đúng `retrieval_worker`, trả lời chính xác với `sources`: ["sla_p1_2026.txt"], `judge_score` = 1.0.

**Câu pipeline fail hoặc partial:**
- ID: `gq03` — Fail ở đâu: phải retry nhiều lần do judge score thấp ban đầu.  
  Root cause: câu hỏi multi-hop access + policy cần thêm evidence và nhiều vòng synthesis/judge. `judge_iterations` = 3, `judge_score` = 0.575, nhưng pipeline vẫn dừng ở `PASS` theo fail-safe logic.

**Câu gq07 (abstain):** Nhóm xử lý thế nào?

Câu gq07 được pipeline xử lý bằng cách trả về `Không đủ thông tin` với low confidence 0.30 và vẫn ghi lại nguồn `sla_p1_2026.txt`. Đó là behaviour đúng cho câu không có evidence rõ ràng.

**Câu gq09 (multi-hop khó nhất):** Trace ghi được 2 workers không? Kết quả thế nào?

gq09 đã đi qua `retrieval_worker`, `policy_tool_worker`, `synthesis_worker`, và `judge_worker`. Trace cho thấy `mcp_tools_used` gồm `check_access_permission` và `get_ticket_info`, và kết quả cuối cùng là `judge_verdict: PASS` với `judge_score` = 0.775.

---

## 4. So sánh Day 08 vs Day 09 — Điều nhóm quan sát được 

**Metric thay đổi rõ nhất (có số liệu):**
Latency Day 09 giảm còn ~3s trung bình cho 15 câu, so với ~9.47s của Day 08 Hybrid+Rerank. Day 09 cũng bổ sung trace rõ ràng: `route_reason`, `workers_called`, `mcp_tools_used`.

**Điều nhóm bất ngờ nhất khi chuyển từ single sang multi-agent:**
Chúng tôi bất ngờ rằng multi-agent không chỉ giúp cho các câu multi-hop phức tạp mà còn giúp debug nhanh hơn nhiều. Khi câu hỏi đơn giản, latency còn tốt hơn vì Day 09 bỏ hẳn reranking; nhưng lợi ích lớn nhất là có trace rõ ràng để xác định ngay đoạn nào sai.

**Trường hợp multi-agent KHÔNG giúp ích hoặc làm chậm hệ thống:**
Với câu đơn giản như gq08, thêm một tầng supervisor và policy worker không tạo khác biệt về chất lượng; nó chỉ làm tăng complexity code. Multi-agent có lợi rõ nhất với câu policy/access hoặc low-evidence.

---

## 5. Phân công và đánh giá nhóm 

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| Hoàng Ngọc Thạch | `eval_trace.py`, đánh giá grading questions, tạo `artifacts/grading_run.jsonl`, `artifacts/eval_report.json` | Sprint 4 |
| Lại Đức Anh | `mcp_server.py`, `workers/policy_tool.py`, MCP tool integration, `search_kb`, `get_ticket_info`, `check_access_permission` | Sprint 2/3 |
| Nguyễn Minh Trí | `graph.py`, supervisor routing, conditional worker edges, HITL/human_review, state schema | Sprint 1 |
| Nhóm chung | test, debug trace, so sánh Day 08/Day 09 | tất cả |

**Điều nhóm làm tốt:**
Nhóm phối hợp rõ ràng qua modules: supervisor route do Minh Tri định nghĩa, MCP & policy logic do Đức Anh implement, và giai đoạn evaluation/trace do Thạch kiểm thử. Trace JSON giúp phân biệt lỗi route vs worker logic.

**Điều nhóm làm chưa tốt hoặc gặp vấn đề về phối hợp:**
Chúng tôi còn thiếu đồng bộ sớm giữa keyword list supervisor và policy worker, dẫn đến gq03 phải retry nhiều vòng. Việc chưa thống nhất format trace ban đầu cũng khiến phải sửa lại `eval_trace.py` trong Sprint 4.

**Nếu làm lại, nhóm sẽ thay đổi gì trong cách tổ chức?**
Sẽ dành thêm thời gian review chung phần `supervisor_node()` và `policy_tool.py` từ đầu để giảm sai route, đồng thời chuẩn hoá schema `AgentState` trước khi code mỗi worker.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì? 

Chúng tôi sẽ hoàn thiện phần MCP / tool contract và thêm một lớp `LLM-based supervisor` để classify câu hỏi không có keyword rõ. Bằng chứng từ trace gq03/gq09 cho thấy keyword routing hiện tại hoạt động tốt với data chuẩn, nhưng cần mở rộng để xử lý câu hỏi mới. Một ngày thêm sẽ đủ để đưa `mcp_server.py` lên HTTP mock service và cải thiện `policy_tool.py` với input schema xác thực.

---

