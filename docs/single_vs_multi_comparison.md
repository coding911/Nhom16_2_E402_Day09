# Single Agent vs Multi-Agent Comparison — Lab Day 09

**Nhóm:** 16_2_E402 
**Ngày:** 14/04/2026

> Số liệu thực tế:
> - Day 08: `evaluation_report.json` — 10 câu, 3 config (Dense / Hybrid / Hybrid+Rerank), thang 0-5
> - Day 09: `artifacts/eval_report.json` — 15 câu, supervisor-worker + MCP, thang confidence 0-1

---

## 1. Day 08 — So sánh 3 Config Retrieval (Single Agent)

| Metric (thang /5) | Baseline (Dense) | Variant 1 (Hybrid) | Variant 2 (Hybrid+Rerank) | Winner |
|-------------------|-----------------|-------------------|--------------------------|--------|
| Faithfulness | 1.45 | 1.45 | **1.50** | Variant 2 |
| Answer Relevance | 1.65 | 2.30 | **2.65** | Variant 2 |
| Context Recall | 1.00 | 1.00 | 1.00 | Tie |
| Completeness | 2.15 | 2.90 | **3.10** | Variant 2 |
| Latency (s) | **4.74** | 8.94 | 9.47 | Baseline |

**Kết luận Day 08:** Hybrid+Rerank đạt 3/4 metric chất lượng. Context Recall bằng nhau ở cả 3 config — cho thấy bottleneck nằm ở chunking (chunk ~32 tokens quá nhỏ) chứ không phải retrieval strategy. Latency của Hybrid+Rerank cao hơn gấp đôi Dense, nhưng improvement về Relevance (+0.99) và Completeness (+0.95) đủ justify.

**Config tốt nhất Day 08:** Hybrid+Rerank — dùng làm baseline so sánh với Day 09.

---

## 2. Metrics Comparison — Day 08 (Best) vs Day 09 Multi-Agent

> **Lưu ý:** Hai hệ thống dùng thang đo khác nhau nên không so sánh trực tiếp số. Phân tích theo chiều dọc (behavior, capability, structure).

| Dimension | Day 08 — Hybrid+Rerank | Day 09 — Multi-Agent | Ghi chú |
|-----------|----------------------|---------------------|---------|
| Faithfulness | 1.50/5.00 (30%) | N/A (thang khác) | Day 09 dùng cosine confidence |
| Answer Relevance | 2.65/5.00 (53%) | N/A | Thang đo khác — không so được |
| Context Recall | 1.00/5.00 (20%) | N/A | Cả hai đều bị bottleneck chunking |
| Completeness | 3.10/5.00 (62%) | Tốt hơn (ước tính +10%) | Day 09 có policy_tool xử lý exception rõ |
| Avg confidence | N/A | 0.569/1.00 | Dựa trên cosine similarity chunks |
| Avg latency | 9.47s (Hybrid+Rerank) | ~3.0s (warm, 15 câu) | Day 09 nhanh hơn vì không rerank |
| Abstain rate | ~10% (1/10 câu: VIP refund) | 13% (2/15: ERR-403, low conf) | Day 09 abstain đúng hơn |
| Hallucination cases | 1 rõ (ERR-403: bịa quy trình) | 0 hallucination rõ ràng | Key improvement |
| Multi-hop accuracy | ~55% | ~67% (2/3 hard cases đúng) |  |
| Routing visibility | Không có | Có — route_reason + workers_called | Structural improvement |
| HITL capability | Không có | Có — 1/15 trigger | ERR-403 trigger đúng |
| MCP tool calls | Không có | 3/15 câu (20%) | check_access + get_ticket |
| Debug time (ước tính) | 15-20 phút/bug | 3-5 phút/bug | Nhờ trace rõ ràng |

---

## 3. Phân tích theo loại câu hỏi

### 3.1 Câu hỏi đơn giản (single-document)

| Nhận xét | Day 08 (Hybrid+Rerank) | Day 09 |
|---------|----------------------|--------|
| Accuracy | Tốt — Faithfulness 1.50/5 | Tốt — answer grounded, conf ~0.60-0.65 |
| Latency | 9.47s | ~1.3-2.0s (warm) |
| Observation | Đôi khi thiếu điều kiện phụ | Answer tương đương, citation rõ hơn |

**Kết luận:** Multi-agent không có improvement đáng kể với câu đơn giản. Overhead thêm (2-3 worker hops) mà kết quả tương đương. Bù lại, Day 09 nhanh hơn vì không có reranking step.

### 3.2 Câu hỏi multi-hop (cross-document)

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | Kém — miss multi-doc (gq02 penalty, gq05 zero, gq06 partial) | ~67% — 2/3 câu hard đúng |
| Routing visible? | Không | Có — route_reason + mcp_tools_used |
| Observation | Hallucinate khi thiếu context, không abstain | policy_tool + MCP bổ sung context |

**Kết luận:** Multi-agent cải thiện rõ ở multi-hop nhờ retrieval-first + policy_tool có MCP để bổ sung access info. Day 08 bị penalty (gq02) vì hallucinate thay vì abstain.

### 3.3 Câu hỏi cần abstain

| Nhận xét | Day 08 | Day 09 |
|---------|--------|--------|
| Abstain rate | ~10% (1/10) | 13% (2/15) |
| Hallucination | 1 rõ (ERR-403: bịa HTTP 403 xử lý) | 0 hallucination rõ |
| HITL | Không có | ERR-403 → HITL trigger → abstain đúng |

**Kết luận:** Day 09 cải thiện rõ nhất ở abstain behavior. HITL + low confidence signal giúp pipeline không hallucinate với câu hỏi không có evidence trong KB.

---

## 4. Debuggability Analysis

### Day 08 — Debug workflow
```
Khi answer sai → đọc toàn bộ rag_answer.py code → tìm lỗi ở indexing/chunking/retrieval/prompt
Không có trace → không biết bắt đầu từ đâu
Không có routing log → không biết câu nào được handle theo luồng nào
Thời gian ước tính: 15-20 phút để isolate 1 bug

Ví dụ thực tế (Day 08):
  gq02: hallucinate multi-doc → không biết retrieval thiếu hay prompt sai → phải trace cả pipeline
  gq05: zero điểm → không có signal nào để debug nhanh
```

### Day 09 — Debug workflow
```
Khi answer sai → đọc trace JSON → xem supervisor_route + route_reason
  → Route sai? → sửa keyword list trong supervisor_node()
  → Retrieval kém? → python workers/retrieval.py (test độc lập)
  → Policy sai? → python workers/policy_tool.py (test độc lập)
  → Synthesis sai? → kiểm tra context trong worker_io_logs
Thời gian ước tính: 3-5 phút để isolate 1 bug

Ví dụ thực tế (Day 09):
  q09 ERR-403: đọc trace → supervisor_route=human_review, hitl_triggered=True,
  retrieved_chunks=[] → biết ngay: không có doc về ERR-403 → synthesis abstain đúng
  Debug time: <2 phút
```

---

## 5. Extensibility Analysis

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Thêm 1 API mới (VD: Jira) | Phải sửa rag_answer.py prompt + retrieval | Thêm tool vào mcp_server.py |
| Thêm domain mới (VD: legal) | Re-index + sửa prompt | Thêm worker mới hoặc extend routing |
| Thay retrieval strategy | Sửa trực tiếp trong pipeline | Sửa retrieval_worker.py độc lập |
| A/B test một phần | Clone toàn pipeline | Swap worker, giữ nguyên graph |
| Thêm compliance check | Hard-code vào prompt | Thêm policy_tool exception rule |

---

## 6. Cost & Latency Trade-off

| Scenario | Day 08 LLM calls | Day 09 LLM calls |
|---------|-----------------|-----------------|
| Simple query | 1 (synthesis) | 1 (synthesis) |
| Complex query (policy) | 1 | 1 + 1-2 MCP calls (local, 0 API cost) |
| Reranking overhead | +4.73s (vs dense) | Không có reranking |
| Embedding overhead | 1 call | 1 call (cached, ~1ms warm) |

**Nhận xét:** Day 09 không tốn thêm LLM calls so với Day 08. MCP tools là local Python function (0 latency, 0 API cost). Day 09 còn nhanh hơn Day 08 Hybrid+Rerank vì bỏ reranking step. Overhead thực tế: +200-500ms cho ChromaDB query + worker function calls.

---

## 7. Kết luận

### Multi-agent tốt hơn single agent ở:

1. **Abstain & anti-hallucination** — HITL + confidence signal: ERR-403 trigger human_review → abstain đúng thay vì hallucinate (như Day 08 đã làm với gq02).
2. **Exception handling chính xác** — policy_tool_worker xử lý Flash Sale, digital product, access control bằng rule-based logic rõ ràng, không phụ thuộc vào LLM "nhớ" đúng exception.
3. **Debuggability** — Trace rõ ràng với route_reason, workers_called, worker_io_logs. Debug time giảm từ 15-20 phút xuống 3-5 phút.
4. **Extensibility qua MCP** — Thêm capability mà không sửa core pipeline.
5. **Latency thấp hơn** — Day 09 (~3.0s warm) vs Day 08 Hybrid+Rerank (~9.5s). Day 09 không cần rerank step.

### Multi-agent kém hơn hoặc không khác biệt ở:

1. **Câu hỏi đơn giản** — Kết quả tương đương nhưng multi-agent có overhead về code complexity.
2. **Setup phức tạp hơn** — Phải maintain nhiều file, state schema, worker contracts.
3. **Scoring metrics khác nhau** — Khó so sánh trực tiếp Faithfulness/Relevance với Confidence.

### Khi nào KHÔNG nên dùng multi-agent:
- Bài toán đơn giản (1 loại câu hỏi, 1 data source, không cần routing)
- Prototype nhanh — single agent trước, refactor sang multi-agent khi cần scale
- Team nhỏ, maintenance cost cao

### Nếu tiếp tục phát triển:
- Thêm LLM-as-Judge để đo Faithfulness/Relevance cho Day 09 (để so sánh apples-to-apples với Day 08)
- Thay keyword routing bằng LLM classifier để handle câu không có keyword rõ
- Implement HITL thật với LangGraph `interrupt_before` + Slack notification
- Implement hybrid retrieval (BM25 + dense) để cải thiện Context Recall (hiện tại = 1.00/5 ở Day 08)