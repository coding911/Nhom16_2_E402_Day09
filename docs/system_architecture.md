# System Architecture — Lab Day 09

**Nhóm:** 16_2_E402
**Ngày:** 14/04/2026

---

## 1. Tổng quan kiến trúc

**Pattern đã chọn:** Supervisor-Worker + Judge Retry Loop (LangGraph StateGraph)
**Lý do chọn pattern này (thay vì single agent):**

Bài toán trợ lý nội bộ CS + IT Helpdesk có hai luồng xử lý khác nhau: (1) tra cứu thông tin từ knowledge base (SLA, HR policy) và (2) kiểm tra policy phức tạp có exception/edge case (Flash Sale, access control). Single agent phải xử lý cả hai luồng trong một prompt → khó debug, khó mở rộng. Supervisor-Worker cho phép mỗi worker chuyên môn hóa một nhiệm vụ, dễ test độc lập, và có thể extend qua MCP mà không sửa core. Thêm Judge Worker tạo vòng lặp tự cải thiện: synthesis → evaluate → retry nếu chưa đạt ngưỡng chất lượng.

---

## 2. Sơ đồ Pipeline

```
User Request (câu hỏi)
        │
        ▼
┌───────────────────────────────┐
│         Supervisor            │
│  - Phân tích task keywords    │
│  - Set route, risk_high,      │
│    needs_tool                 │
│  - Ghi route_reason           │
└──────────────┬────────────────┘
               │ [LangGraph conditional edge]
               │
    ┌──────────┴──────────┐
    │                     │
    ▼                     ▼
human_review        retrieval_worker ◄──────────────────┐
(HITL auto-          (ChromaDB dense search)            │
 approve)                    │                          │
    │               [conditional edge]                  │
    │                        │                          │
    │              ┌─────────┴─────────┐                │
    │              │                   │                │
    └──────────────►  policy_tool_worker  synthesis_worker│
                   │  - Phân tích policy │              │
                   │  - Gọi MCP tools   │              │
                   └────────┬──────────┘              │
                            │                          │
                            ▼                          │
                   synthesis_worker ◄──────────────────┘
                    - Build context từ chunks           │ (retry với feedback)
                    - Call LLM (gpt-4o-mini)            │
                    - Add citation [source]             │
                    - Compute confidence                │
                            │                          │
                            ▼                          │
                    ┌───────────────┐                  │
                    │  Judge Worker │                  │
                    │ LLM-as-Judge  │                  │
                    │ - faithfulness│   RETRY          │
                    │ - completeness│ ─────────────────┘
                    │ - relevance   │ (score < 0.70 AND
                    └───────┬───────┘  iter < MAX_RETRIES)
                            │
                          PASS
                            │
                            ▼
                     Final Answer + Trace
          (final_answer, confidence, sources,
           judge_score, judge_verdict, judge_iterations,
           route_reason, workers_called, mcp_tools_used,
           latency_ms, timestamp)
```

**Ghi chú thực tế:**
- Graph dùng **LangGraph StateGraph** với `add_conditional_edges()`.
- Khi route = `policy_tool_worker`, thứ tự: `retrieval_worker → policy_tool_worker → synthesis_worker → judge_worker`
- Judge retry tối đa **2 lần** (`MAX_RETRIES=2`), ngưỡng PASS = **0.70**.
- Nếu judge lỗi (LLM fail) → fail-safe PASS để không block pipeline.

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích task, quyết định route, flag risk_high và needs_tool |
| **Input** | `task` (str) từ AgentState |
| **Output** | `supervisor_route`, `route_reason`, `risk_high`, `needs_tool` |
| **Routing logic** | Keyword matching: policy_keywords → policy_tool_worker, retrieval_keywords → retrieval_worker, ERR- + risk → human_review |
| **HITL condition** | `risk_high=True` AND task chứa `err-` (mã lỗi không rõ) |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Embed query → query ChromaDB → trả về top-k chunks có relevance score |
| **Embedding model** | `all-MiniLM-L6-v2` (SentenceTransformers, offline) |
| **Top-k** | 3 (có thể cấu hình qua `retrieval_top_k` trong state) |
| **Stateless?** | Yes — không giữ state giữa các lần gọi (model được cache module-level) |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích policy exception từ retrieved chunks, gọi MCP tools khi cần thêm context |
| **MCP tools gọi** | `check_access_permission` (khi có access keywords), `get_ticket_info` (khi có ticket/P1) |
| **Exception cases xử lý** | Flash Sale, digital product/license key, activated product, temporal scoping (đơn trước 01/02/2026) |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | `gpt-4o-mini` (OpenAI) |
| **Temperature** | 0.1 (low — để grounded, giảm hallucination) |
| **Grounding strategy** | System prompt nghiêm ngặt: "CHỈ dùng context, KHÔNG dùng kiến thức ngoài" |
| **Abstain condition** | Nếu không có chunks hoặc context không đủ → trả về "Không đủ thông tin trong tài liệu nội bộ" |
| **Retry support** | Nhận `judge_feedback` từ state → thêm vào prompt khi đang retry |

### Judge Worker (`workers/judge.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Đánh giá câu trả lời từ synthesis, quyết định PASS hoặc RETRY |
| **LLM model** | `gpt-4o-mini` (OpenAI), `temperature=0.0` (deterministic) |
| **Scoring dimensions** | `faithfulness` (×0.4) + `completeness` (×0.35) + `relevance` (×0.25) |
| **PASS threshold** | `overall_score >= 0.70` → PASS → END |
| **RETRY condition** | `overall_score < 0.70` AND `judge_iterations < MAX_RETRIES` (=2) |
| **Fail-safe** | Nếu LLM judge lỗi → auto PASS (không block pipeline) |
| **Feedback loop** | Khi RETRY: ghi `judge_feedback` vào state → synthesis đọc và cải thiện |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| `search_kb` | query (str), top_k (int) | chunks (list), sources (list), total_found (int) |
| `get_ticket_info` | ticket_id (str) | ticket details: priority, status, assignee, sla_deadline |
| `check_access_permission` | access_level (int), requester_role (str), is_emergency (bool) | can_grant, required_approvers, emergency_override, notes |
| `create_ticket` | priority (str), title (str), description (str) | ticket_id, url, created_at |

---

## 4. Shared State Schema

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------|
| `task` | str | Câu hỏi đầu vào từ user | supervisor đọc |
| `supervisor_route` | str | Worker được chọn | supervisor ghi |
| `route_reason` | str | Lý do route chi tiết với keywords | supervisor ghi |
| `risk_high` | bool | Flag rủi ro cao → HITL hoặc human_review | supervisor ghi |
| `needs_tool` | bool | True khi route = policy_tool_worker | supervisor ghi |
| `retrieved_chunks` | list | Evidence từ retrieval (text, source, score, metadata) | retrieval ghi, policy_tool/synthesis đọc |
| `retrieved_sources` | list | Danh sách file nguồn duy nhất | retrieval ghi |
| `policy_result` | dict | policy_applies, exceptions_found, access_check | policy_tool ghi, synthesis đọc |
| `mcp_tools_used` | list | Trace từng MCP call: tool, input, output, timestamp | policy_tool ghi |
| `mcp_access_result` | dict | Kết quả từ `check_access_permission` | policy_tool ghi |
| `hitl_triggered` | bool | True nếu đã qua human_review node | human_review ghi |
| `final_answer` | str | Câu trả lời cuối có citation | synthesis ghi |
| `confidence` | float | Mức tin cậy (0.0-1.0), dựa trên chunk scores | synthesis ghi |
| `sources` | list | Nguồn được cite trong answer | synthesis ghi |
| `judge_score` | float | Điểm tổng hợp từ judge (0.0-1.0) | judge ghi |
| `judge_feedback` | str | Feedback cụ thể để synthesis cải thiện (xóa sau khi dùng) | judge ghi, synthesis đọc |
| `judge_verdict` | str | "PASS" hoặc "RETRY" | judge ghi, graph đọc để route |
| `judge_iterations` | int | Số lần judge đã chạy (giới hạn MAX_RETRIES=2) | judge ghi |
| `workers_called` | list | Thứ tự workers đã được gọi | mỗi worker ghi tên mình |
| `worker_io_logs` | list | Trace input/output từng worker | mỗi worker ghi |
| `latency_ms` | int | Tổng thời gian từ start đến end (ms) | graph ghi |
| `timestamp` | str | ISO timestamp khi hoàn thành | graph ghi |
| `run_id` | str | ID duy nhất cho mỗi run | make_initial_state() tạo |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — không rõ lỗi ở retrieval hay generation | Dễ hơn — xem route_reason + test worker độc lập |
| Thêm capability mới | Phải sửa toàn prompt + RAG chain | Thêm MCP tool hoặc worker riêng |
| Routing visibility | Không có | Có `route_reason` + `workers_called` trong trace |
| Exception handling | Nằm trong LLM prompt → không nhất quán | policy_tool_worker xử lý rule-based, rõ ràng |
| Scalability | Tất cả logic trong 1 hàm | Mỗi worker thay thế được độc lập |

**Quan sát từ lab thực tế:**
Câu q09 (ERR-403-AUTH): Day 08 hallucinate (bịa quy trình xử lý), Day 09 trigger HITL + abstain đúng. Nguyên nhân: supervisor detect `err-` + risk_high → human_review → downstream synthesis nhận không đủ context → abstain.

---

## 6. Giới hạn và điểm cần cải tiến

1. **Routing bằng keyword matching** — dễ sai với câu hỏi không có keyword rõ ràng. Nên nâng cấp lên LLM-based classifier cho routing phức tạp hơn.
2. **Policy_tool chỉ check rule-based** — `analyze_policy()` dùng keyword check đơn giản. Với câu hỏi temporal scoping phức tạp (q12), cần LLM để phân tích chính xác hơn.
3. **HITL là auto-approve** — trong production cần implement interrupt thật với LangGraph `interrupt_before` hoặc human-in-the-loop queue.
4. **Confidence metric không chuẩn hóa** — hiện dựa trên cosine similarity của chunks, không phải đánh giá câu trả lời. Cần LLM-as-Judge để confidence chính xác hơn.