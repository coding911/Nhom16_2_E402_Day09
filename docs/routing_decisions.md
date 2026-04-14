# Routing Decisions Log — Lab Day 09

**Nhóm:** 16_2_E402
**Ngày:** 14/04/2026

> Dữ liệu lấy từ trace thực tế trong `artifacts/traces/` — chạy 15 test questions ngày 14/04/2026.

---

## Routing Decision #1 — Câu hỏi SLA đơn giản

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `knowledge base lookup keywords detected: ['p1', 'sla', 'ticket']`  
**MCP tools được gọi:** Không có  
**Workers called sequence:** `['retrieval_worker', 'synthesis_worker']`

**Kết quả thực tế:**
- final_answer: "Ticket P1 có SLA phản hồi ban đầu 15 phút kể từ khi ticket được tạo. Thời gian xử lý và khắc phục là 4 giờ..."
- confidence: 0.58
- Correct routing? Yes — đúng expected_route trong test_questions.json

**Nhận xét:** Routing hoàn toàn đúng. Keywords `p1`, `sla`, `ticket` match rõ ràng. Confidence 0.58 thấp hơn mong đợi vì cosine similarity của chunks trong khoảng 0.55-0.65, không phản ánh chính xác chất lượng answer (answer thực tế rất tốt, faithful với docs).

---

## Routing Decision #2 — Câu hỏi Access Control với MCP

**Task đầu vào:**
> "Contractor cần Admin Access (Level 3) để khắc phục sự cố P1 đang active. Quy trình cấp quyền tạm thời như thế nào?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `policy/access keywords detected: ['cấp quyền', 'level 3', 'contractor'] → MCP tools will be invoked | risk_high: ['khẩn cấp']`  
**MCP tools được gọi:** `check_access_permission` (level=3, role=contractor, emergency=True), `get_ticket_info` (P1-LATEST)  
**Workers called sequence:** `['retrieval_worker', 'policy_tool_worker', 'synthesis_worker']`

**Kết quả thực tế:**
- final_answer: "Level 3 (Admin Access) KHÔNG có emergency bypass theo SOP. Dù đang có P1 khẩn cấp, vẫn phải có approval đầy đủ từ Line Manager, IT Admin và IT Security..."
- confidence: 0.66
- Correct routing? Yes — đúng expected_route `policy_tool_worker`

**Nhận xét:** Routing chuẩn. Đây là câu multi-hop khó nhất (q13) — cần cross-document từ access_control_sop.txt và sla_p1_2026.txt. MCP `check_access_permission` trả về `can_grant=True` nhưng `emergency_override=False` cho Level 3 — synthesis tổng hợp đúng là "KHÔNG có emergency bypass". Kết quả khớp với expected answer.

---

## Routing Decision #3 — HITL Trigger với ERR code

**Task đầu vào:**
> "ERR-403-AUTH là lỗi gì và cách xử lý?"

**Worker được chọn:** `human_review` (→ tự động approve → `retrieval_worker`)  
**Route reason (từ trace):** `unknown error code detected + risk_high → escalate to human review`  
**MCP tools được gọi:** Không có  
**Workers called sequence:** `['human_review', 'retrieval_worker', 'synthesis_worker']`

**Kết quả thực tế:**
- final_answer: "Không tìm thấy thông tin về mã lỗi ERR-403-AUTH trong tài liệu nội bộ hiện có..."
- confidence: 0.30 (low — không đủ evidence)
- hitl_triggered: true
- Correct routing? Acceptable — expected_route là `retrieval_worker`, nhưng HITL→retrieval là behavior tốt hơn (safe-by-default khi không có context)

**Nhận xét:** Supervisor detect `err-` trong task → set `risk_high=True` → route sang `human_review`. Trong lab mode auto-approve, pipeline tiếp tục với retrieval nhưng không có document nào match ERR-403-AUTH → synthesis abstain đúng với confidence thấp (0.30). **So với Day 08**: Day 08 hallucinate (bịa quy trình xử lý HTTP 403). Day 09 abstain đúng — đây là improvement rõ ràng nhất của multi-agent.

---

## Routing Decision #4 — Multi-hop phức tạp nhất

**Task đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor để thực hiện emergency fix. Đồng thời cần notify stakeholders theo SLA. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker`  
**Route reason:** `policy/access keywords detected: ['level 2', 'contractor'] → MCP tools will be invoked | risk_high: ['2am', 'khẩn cấp']`  
**MCP tools được gọi:** `check_access_permission` (level=2, role=contractor, emergency=True), `get_ticket_info` (P1-LATEST)

**Nhận xét: Đây là trường hợp routing khó nhất trong lab. Tại sao?**

Câu q15 yêu cầu trả lời **hai quy trình song song** từ **hai tài liệu khác nhau**: SLA P1 notification (sla_p1_2026.txt) và Level 2 emergency bypass (access_control_sop.txt). Supervisor chỉ route sang một worker — không thể route đồng thời. Giải pháp hiện tại: `policy_tool_worker` chạy sau `retrieval_worker` (retrieval lấy chunks từ cả hai docs), rồi MCP `check_access_permission` bổ sung access info. Synthesis tổng hợp từ tất cả sources. Kết quả: answer đúng nhưng latency cao nhất (5218ms) vì 3 workers + 2 MCP calls.

---

## Routing Decision #5 — Judge Worker: PASS ngay lần đầu (trường hợp điển hình)

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker flow:** `retrieval_worker → synthesis_worker → judge_worker → END`  
**Judge input:** answer="Ticket P1 có SLA phản hồi ban đầu 15 phút... Thời gian xử lý 4 giờ [sla_p1_2026.txt]"

**Judge output (từ trace thực tế):**
```json
{
  "faithfulness": 1.0,
  "completeness": 0.95,
  "relevance": 1.0,
  "overall": 0.975,
  "verdict": "PASS",
  "feedback": ""
}
```

**Kết quả:** `judge_score=0.975, verdict=PASS, judge_iterations=1`

**Nhận xét:** Câu SLA đơn giản — context đầy đủ, answer hoàn toàn grounded, không cần retry. Judge PASS ngay lần đầu. Đây là pattern phổ biến nhất: 14/15 câu PASS lần đầu, không cần synthesis retry.

---

## Routing Decision #6 — Judge Worker: RETRY khi answer thiếu detail

**Task đầu vào (giả lập lab để test retry path):**
> "Contractor cần Admin Access Level 3 để fix P1 khẩn cấp. Quy trình cấp quyền tạm thời?"

**Scenario:** Synthesis lần đầu trả lời ngắn: "Liên hệ IT Admin để cấp quyền tạm thời."

**Judge output lần 1:**
```json
{
  "faithfulness": 0.80,
  "completeness": 0.40,
  "relevance": 0.70,
  "overall": 0.617,
  "verdict": "RETRY",
  "feedback": "Câu trả lời thiếu: (1) số lượng approvers cần thiết (Line Manager + IT Admin + IT Security), (2) khẳng định rõ Level 3 KHÔNG có emergency bypass dù P1 khẩn cấp."
}
```

**Synthesis retry:** Nhận feedback → thêm vào prompt → generate lại với detail đầy đủ.

**Judge output lần 2:**
```json
{
  "faithfulness": 1.0,
  "completeness": 0.95,
  "relevance": 0.90,
  "overall": 0.965,
  "verdict": "PASS",
  "feedback": ""
}
```

**Kết quả:** `judge_score=0.965, verdict=PASS, judge_iterations=2`

**Nhận xét:** Đây là use case minh họa rõ nhất giá trị của Judge loop. Answer lần đầu "đúng nhưng thiếu" — đủ để qua HITL nhưng không đủ detail cho câu multi-condition. Sau RETRY với feedback cụ thể, synthesis bổ sung đủ approvers và no-emergency-bypass clause. Judge loop thay thế cho việc LLM tự judge độ đầy đủ của mình (vốn không reliable).

---

## Tổng kết

### Routing Distribution (15 test questions)

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | 9 | 60% |
| policy_tool_worker | 6 | 40% |
| human_review | 1 | 7% (→ auto-approve → retrieval) |

*(q09 được route sang human_review trước, sau đó tiếp tục retrieval_worker)*

### Routing Accuracy

- Câu route đúng: 14/15 (93%)
- Câu route khác expected (nhưng acceptable): 1/15 — q09 (expected: retrieval_worker, thực tế: human_review→retrieval, outcome: correct abstain)
- Câu trigger HITL: 1 (q09 ERR-403-AUTH)

### Judge Routing Distribution (15 test questions)

| Verdict | Số câu | % tổng |
|---------|--------|--------|
| PASS (lần 1, iter=1) | 14 | 93% |
| RETRY → PASS (iter=2) | 0 | 0% (trong run thực tế; test case retry ở Decision #6 là lab demo) |
| PASS forced (iter=MAX) | 0 | 0% |

**Nhận xét:** 14/15 câu PASS ngay lần đầu với judge_score trung bình 0.975–1.0. Điều này cho thấy synthesis_worker với context đầy đủ đã tạo ra answer chất lượng cao. Judge loop có giá trị nhiều hơn khi context kém hoặc câu hỏi multi-condition phức tạp.

### Lesson Learned về Routing

1. **Keyword matching đủ dùng cho bài toán này** — 14/15 routing đúng với simple keyword matching. Không cần LLM classifier cho tập từ khóa đủ rõ ràng. Trade-off: dễ fail với câu không có keyword rõ.
2. **Risk_high flag cần cân nhắc kỹ** — `err-` keyword trigger HITL là đúng với mã lỗi thật (ERR-403 unknown), nhưng sẽ fail nếu user hỏi "err-or handling là gì" (false positive). Cần test thêm edge cases.
3. **Retrieval-first ordering quan trọng** — chạy retrieval trước policy_tool giúp policy_tool có đủ context từ ChromaDB trước khi gọi MCP. Ngược lại sẽ gọi MCP search_kb (fallback) thay vì dùng chunks đã có.
4. **Judge routing là conditional edge không phải keyword** — khác với supervisor routing, judge dùng score threshold (0.70) để route. Tách biệt hoàn toàn: supervisor quyết định "ai làm", judge quyết định "đã làm đủ chưa".

### Route Reason Quality

`route_reason` hiện tại đủ thông tin để debug: ghi rõ keywords matched và worker được chọn, thêm `→ MCP tools will be invoked` khi cần. Judge verdict và score được ghi riêng trong `judge_verdict` và `judge_score` (không phải route_reason). Cải tiến tiếp theo: thêm `judge_feedback` vào trace khi RETRY để dễ audit.