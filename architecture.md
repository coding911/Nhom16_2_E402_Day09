# Kiến trúc hệ thống — Day 09 Lab: Multi-Agent Orchestration

## Tổng quan

Hệ thống IT Helpdesk nội bộ theo pattern **Supervisor-Worker**, nhận câu hỏi từ user, tự động route sang worker phù hợp, tổng hợp câu trả lời có trích dẫn nguồn.

```
User Input
    ↓
[graph.py] — Supervisor Orchestrator
    ↓
supervisor_node() — phân tích task, quyết định route
    ↓
route_decision() — conditional edge
    ↙            ↓              ↘
retrieval    policy_tool    human_review
_worker      _worker        _node (HITL)
    ↘            ↙
  synthesis_worker
    ↓
final_answer + sources + confidence
```

---

## Các thành phần

### `graph.py` — Orchestrator

Entry point của hệ thống. Điều phối toàn bộ pipeline.

**AgentState** (`TypedDict`) — shared state đi xuyên graph:

| Field | Kiểu | Mô tả |
|-------|------|-------|
| `task` | str | Câu hỏi đầu vào |
| `supervisor_route` | str | Worker được chọn |
| `route_reason` | str | Lý do routing |
| `risk_high` | bool | Flag cần HITL |
| `needs_tool` | bool | Flag cần MCP tool |
| `retrieved_chunks` | list | Chunks từ retrieval |
| `policy_result` | dict | Kết quả policy check |
| `mcp_tools_used` | list | Danh sách MCP calls |
| `final_answer` | str | Câu trả lời cuối |
| `confidence` | float | Mức tin cậy (0–1) |
| `history` | list | Trace từng bước |

**Routing logic trong `supervisor_node`:**

```
keywords: ["hoàn tiền", "refund", "flash sale", "license", "access"] → policy_tool_worker
keywords: ["emergency", "khẩn cấp", "err-"] → risk_high = True
risk_high AND "err-" → human_review
còn lại → retrieval_worker (default)
```

**Luồng thực thi (`build_graph`):**

```
human_review  → auto-approve → retrieval_worker → synthesis_worker
policy_tool   → [retrieval nếu chưa có chunks]  → synthesis_worker
retrieval     →                                     synthesis_worker
```

Hiện dùng **Option A** (Python if/else thuần). Có thể chuyển sang **Option B** (LangGraph `StateGraph` với conditional edges).

---

### `workers/retrieval.py` — Retrieval Worker

Dense retrieval từ ChromaDB.

```
query
  → SentenceTransformer("all-MiniLM-L6-v2").encode()
  → ChromaDB.query(cosine similarity)
  → top-k chunks: {"text", "source", "score", "metadata"}
```

- Fallback embedding: OpenAI `text-embedding-3-small` → random (test only)
- Collection: `day09_docs` tại `./chroma_db`

---

### `workers/policy_tool.py` — Policy Tool Worker

Kiểm tra policy và gọi MCP tools khi cần.

**Bước 1** — Nếu chưa có chunks: gọi MCP `search_kb`

**Bước 2** — Rule-based exception detection:

| Exception | Trigger keywords | Source |
|-----------|-----------------|--------|
| Flash Sale | "flash sale" | policy_refund_v4.txt |
| Digital product | "license", "subscription", "kỹ thuật số" | policy_refund_v4.txt |
| Activated product | "đã kích hoạt", "đã đăng ký" | policy_refund_v4.txt |
| Old order | "trước 01/02", "31/01" | → flag (policy v3 không có docs) |

**Bước 3** — Nếu cần: gọi MCP `get_ticket_info`

---

### `workers/synthesis.py` — Synthesis Worker

Tổng hợp câu trả lời cuối bằng LLM.

```
chunks + policy_result
  → _build_context()
  → LLM (GPT-4o-mini hoặc Gemini) với system prompt strict
  → final_answer + sources + confidence
```

**System prompt**: chỉ dùng context được cung cấp, không hallucinate, trích dẫn nguồn, nêu rõ exceptions.

**Confidence score:**
```
avg(chunk scores) - 0.05 × số exceptions → clamp [0.1, 0.95]
abstain ("Không đủ thông tin") → 0.3
không có chunks → 0.1
```

---

### `mcp_server.py` — Mock MCP Server

Mô phỏng MCP (Model Context Protocol) interface. Agent gọi `dispatch_tool()` thay vì hard-code từng API.

| Tool | Mô tả |
|------|-------|
| `search_kb(query, top_k)` | Semantic search ChromaDB |
| `get_ticket_info(ticket_id)` | Mock Jira ticket lookup |
| `check_access_permission(level, role, is_emergency)` | Access control SOP |
| `create_ticket(priority, title, description)` | Mock Jira create |

- `list_tools()` ≈ `tools/list` trong MCP protocol
- `dispatch_tool(name, input)` ≈ `tools/call` trong MCP protocol
- `TOOL_SCHEMAS`: schema discovery cho từng tool (JSON Schema)

**Access control rules:**

| Level | Required approvers | Emergency bypass |
|-------|--------------------|-----------------|
| 1 | Line Manager | Không |
| 2 | Line Manager + IT Admin | Có (tạm thời) |
| 3 | Line Manager + IT Admin + IT Security | Không |

---

### `build_index.py` — Offline Indexer

Xây dựng ChromaDB index từ tài liệu nội bộ. Chạy một lần trước khi dùng hệ thống.

```
data/docs/*.txt
  → chunk_text(size=500, overlap=100)
  → SentenceTransformer.encode() theo batch
  → ChromaDB.add() (batch=50)
  → collection "day09_docs" tại ./chroma_db
```

---

## Data flow toàn hệ thống

```
[Offline]
build_index.py → data/docs/*.txt → chunks → ChromaDB (chroma_db/)

[Online]
run_graph(task)
  → make_initial_state()
  → supervisor_node()      : keyword matching → route + flags
  → retrieval_worker       : embed → ChromaDB → chunks
  → policy_tool_worker     : rule check + MCP calls
  → synthesis_worker       : LLM → final_answer
  → save_trace()           : artifacts/traces/{run_id}.json
```

---

## Tech stack

| Layer | Thư viện |
|-------|----------|
| Embedding | `sentence-transformers` (all-MiniLM-L6-v2) |
| Vector store | `chromadb` (PersistentClient, cosine space) |
| LLM | `openai` (gpt-4o-mini) / `google-generativeai` (gemini-1.5-flash) |
| Orchestration | Python if/else (Option A) hoặc `langgraph` (Option B) |
| MCP server | In-process mock / `fastapi` + `mcp` library (Sprint 3 bonus) |

---

## TODO theo Sprint

| Sprint | Task |
|--------|------|
| Sprint 1 | Hoàn thiện routing logic trong `supervisor_node` |
| Sprint 2 | Uncomment worker imports thực trong `graph.py` (bỏ placeholder) |
| Sprint 2 | Upgrade `analyze_policy` lên LLM-based analysis |
| Sprint 3 | HITL thực với LangGraph `interrupt_before` |
| Sprint 3 (bonus) | HTTP MCP server với FastAPI + `mcp` library |
