"""
graph.py — Supervisor Orchestrator (LangGraph)
Kiến trúc: Supervisor-Worker với LangGraph StateGraph + Judge retry loop.

Pipeline:
    Input → Supervisor → [human_review →] retrieval_worker
                                        → [policy_tool_worker →] synthesis_worker
                                                                → judge_worker
                                                                → [RETRY → synthesis_worker | PASS → END]

Chạy thử:
    python graph.py
"""

import json
import os
from datetime import datetime
from typing import TypedDict, Optional
from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, END


# ─────────────────────────────────────────────
# 1. Shared State — dữ liệu đi xuyên toàn graph
# ─────────────────────────────────────────────

class AgentState(TypedDict):
    # Input
    task: str                           # Câu hỏi đầu vào từ user

    # Supervisor decisions
    route_reason: str                   # Lý do route sang worker nào
    risk_high: bool                     # True → cần HITL hoặc human_review
    needs_tool: bool                    # True → cần gọi external tool qua MCP
    hitl_triggered: bool                # True → đã pause cho human review

    # Worker outputs
    retrieved_chunks: list              # Output từ retrieval_worker
    retrieved_sources: list             # Danh sách nguồn tài liệu
    policy_result: dict                 # Output từ policy_tool_worker
    mcp_tools_used: list                # Danh sách MCP tools đã gọi
    mcp_access_result: dict             # Kết quả từ MCP check_access_permission
    worker_io_logs: list                # Log input/output từng worker

    # Final output
    final_answer: str                   # Câu trả lời tổng hợp
    sources: list                       # Sources được cite
    confidence: float                   # Mức độ tin cậy (0.0 - 1.0)

    # Judge / evaluator
    judge_score: float                  # Điểm đánh giá từ judge (0.0 - 1.0)
    judge_feedback: str                 # Phản hồi cụ thể từ judge để synthesis cải thiện
    judge_verdict: str                  # "PASS" hoặc "RETRY"
    judge_iterations: int               # Số lần judge đã chạy (giới hạn retry)

    # Trace & history
    history: list                       # Lịch sử các bước đã qua
    workers_called: list                # Danh sách workers đã được gọi
    supervisor_route: str               # Worker được chọn bởi supervisor
    latency_ms: Optional[int]           # Thời gian xử lý (ms)
    run_id: str                         # ID của run này
    timestamp: str                      # Thời điểm hoàn thành (ISO format)
    retrieval_top_k: int                # Số chunks cần retrieve (default 3)


def make_initial_state(task: str) -> AgentState:
    """Khởi tạo state cho một run mới."""
    return {
        "task": task,
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": {},
        "mcp_tools_used": [],
        "mcp_access_result": {},
        "worker_io_logs": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "judge_score": 0.0,
        "judge_feedback": "",
        "judge_verdict": "",
        "judge_iterations": 0,
        "history": [],
        "workers_called": [],
        "supervisor_route": "",
        "latency_ms": None,
        "timestamp": "",
        "retrieval_top_k": 3,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    }


# ─────────────────────────────────────────────
# 2. Supervisor Node — quyết định route
# ─────────────────────────────────────────────

def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor phân tích task và quyết định:
    1. Route sang worker nào
    2. Có cần MCP tool không
    3. Có risk cao cần HITL không
    """
    task = state["task"].lower()
    state["history"].append(f"[supervisor] received task: {state['task'][:80]}")

    route = "retrieval_worker"
    route_reason = ""
    needs_tool = False
    risk_high = False

    # ── Keywords → policy_tool_worker ──────────────────────────────────
    policy_keywords = [
        "flash sale",
        "license key", "license",
        "subscription", "kỹ thuật số",
        "đã kích hoạt", "đã đăng ký",
        "cấp quyền", "access level",
        "level 3", "level 2",
        "admin access", "elevated access",
        "store credit",
        "31/01", "30/01", "trước 01/02",
        "contractor",
    ]

    # ── Keywords → retrieval_worker ────────────────────────────────────
    retrieval_keywords = [
        "p1", "sla", "ticket", "escalation", "sự cố", "incident",
        "nghỉ phép", "annual leave", "sick leave", "thai sản",
        "remote", "work from home", "wfh",
        "probation",
        "helpdesk", "bị khóa", "đăng nhập sai", "reset password",
    ]

    # ── Keywords → risk_high flag ──────────────────────────────────────
    risk_keywords = [
        "emergency", "khẩn cấp", "2am", "urgent",
        "err-",
    ]

    matched_policy    = [kw for kw in policy_keywords    if kw in task]
    matched_retrieval = [kw for kw in retrieval_keywords if kw in task]
    matched_risk      = [kw for kw in risk_keywords      if kw in task]

    if matched_policy:
        route = "policy_tool_worker"
        route_reason = f"policy/access keywords detected: {matched_policy} → MCP tools will be invoked"
        needs_tool = True
    elif matched_retrieval:
        route = "retrieval_worker"
        route_reason = f"knowledge base lookup keywords detected: {matched_retrieval}"
    else:
        route = "retrieval_worker"
        route_reason = "no specific keyword matched — default to knowledge base search"

    if matched_risk:
        risk_high = True
        route_reason += f" | risk_high: {matched_risk}"

    # Human review override: mã lỗi không rõ + risk
    if risk_high and "err-" in task:
        route = "human_review"
        route_reason = "unknown error code detected + risk_high → escalate to human review"

    state["supervisor_route"] = route
    state["route_reason"] = route_reason
    state["needs_tool"] = needs_tool
    state["risk_high"] = risk_high
    state["history"].append(f"[supervisor] route={route} | reason={route_reason}")

    return state


# ─────────────────────────────────────────────
# 3. Conditional Edges
# ─────────────────────────────────────────────

def route_after_supervisor(state: AgentState) -> str:
    """
    Edge từ supervisor → worker đầu tiên.
    Với policy_tool_worker: vẫn đi qua retrieval trước (retrieval-first ordering).
    """
    route = state.get("supervisor_route", "retrieval_worker")
    if route == "human_review":
        return "human_review"
    # Cả retrieval_worker và policy_tool_worker đều đi qua retrieval trước
    return "retrieval_worker"


def route_after_retrieval(state: AgentState) -> str:
    """
    Edge từ retrieval_worker → policy_tool_worker hoặc synthesis_worker.
    Nếu supervisor_route = policy_tool_worker VÀ chưa qua HITL → policy_tool_worker.
    Còn lại (retrieval_worker route, hoặc sau HITL) → synthesis_worker.
    """
    route = state.get("supervisor_route", "retrieval_worker")
    hitl = state.get("hitl_triggered", False)
    if route == "policy_tool_worker" and not hitl:
        return "policy_tool_worker"
    return "synthesis_worker"


def route_after_judge(state: AgentState) -> str:
    """
    Edge từ judge_worker → synthesis_worker (retry) hoặc END.
    """
    verdict = state.get("judge_verdict", "PASS")
    if verdict == "RETRY":
        return "synthesis_worker"
    return END


# ─────────────────────────────────────────────
# 4. Human Review Node — HITL placeholder
# ─────────────────────────────────────────────

def human_review_node(state: AgentState) -> AgentState:
    """
    HITL node: trong lab mode tự động approve và route tiếp.
    Production: implement với LangGraph interrupt_before + external queue.
    """
    state["hitl_triggered"] = True
    state["history"].append("[human_review] HITL triggered — awaiting human input")
    state["workers_called"].append("human_review")

    print(f"\n⚠️  HITL TRIGGERED")
    print(f"   Task  : {state['task']}")
    print(f"   Reason: {state['route_reason']}")
    print(f"   Action: Auto-approving in lab mode\n")

    # Sau khi approve, chuyển route về retrieval
    state["supervisor_route"] = "retrieval_worker"
    state["route_reason"] += " | human approved → retrieval"

    return state


# ─────────────────────────────────────────────
# 5. Worker Wrappers
# ─────────────────────────────────────────────

from workers.retrieval import run as retrieval_run
from workers.policy_tool import run as policy_tool_run
from workers.synthesis import run as synthesis_run
from workers.judge import run as judge_run


def retrieval_worker_node(state: AgentState) -> AgentState:
    return retrieval_run(state)


def policy_tool_worker_node(state: AgentState) -> AgentState:
    return policy_tool_run(state)


def synthesis_worker_node(state: AgentState) -> AgentState:
    return synthesis_run(state)


def judge_worker_node(state: AgentState) -> AgentState:
    return judge_run(state)


# ─────────────────────────────────────────────
# 6. Build Graph với LangGraph StateGraph
# ─────────────────────────────────────────────

def build_graph():
    """
    Xây dựng LangGraph StateGraph với:
    - Conditional routing từ supervisor
    - Retrieval-first ordering cho policy_tool_worker
    - Judge retry loop: synthesis → judge → [RETRY → synthesis | PASS → END]
    """
    builder = StateGraph(AgentState)

    # ── Thêm nodes ──────────────────────────────────────────────────────
    builder.add_node("supervisor",          supervisor_node)
    builder.add_node("human_review",        human_review_node)
    builder.add_node("retrieval_worker",    retrieval_worker_node)
    builder.add_node("policy_tool_worker",  policy_tool_worker_node)
    builder.add_node("synthesis_worker",    synthesis_worker_node)
    builder.add_node("judge_worker",        judge_worker_node)

    # ── Entry point ──────────────────────────────────────────────────────
    builder.set_entry_point("supervisor")

    # ── Edges ────────────────────────────────────────────────────────────

    # supervisor → human_review hoặc retrieval_worker (policy cũng qua retrieval trước)
    builder.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "human_review":     "human_review",
            "retrieval_worker": "retrieval_worker",
        },
    )

    # human_review → retrieval_worker (sau HITL luôn retrieve)
    builder.add_edge("human_review", "retrieval_worker")

    # retrieval_worker → policy_tool_worker hoặc synthesis_worker
    builder.add_conditional_edges(
        "retrieval_worker",
        route_after_retrieval,
        {
            "policy_tool_worker": "policy_tool_worker",
            "synthesis_worker":   "synthesis_worker",
        },
    )

    # policy_tool_worker → synthesis_worker (luôn)
    builder.add_edge("policy_tool_worker", "synthesis_worker")

    # synthesis_worker → judge_worker (luôn)
    builder.add_edge("synthesis_worker", "judge_worker")

    # judge_worker → synthesis_worker (retry) hoặc END
    builder.add_conditional_edges(
        "judge_worker",
        route_after_judge,
        {
            "synthesis_worker": "synthesis_worker",
            END:                END,
        },
    )

    return builder.compile()


# ─────────────────────────────────────────────
# 7. Public API
# ─────────────────────────────────────────────

_graph = build_graph()


def run_graph(task: str) -> AgentState:
    """
    Entry point: nhận câu hỏi, trả về AgentState với full trace.

    Args:
        task: Câu hỏi từ user

    Returns:
        AgentState với final_answer, judge_score, trace, routing info, v.v.
    """
    import time
    state = make_initial_state(task)
    start = time.time()

    result = _graph.invoke(state)

    result["latency_ms"] = int((time.time() - start) * 1000)
    result["timestamp"] = datetime.now().isoformat()
    result["history"].append(f"[graph] completed in {result['latency_ms']}ms")
    return result


def save_trace(state: AgentState, output_dir: str = "./artifacts/traces") -> str:
    """Lưu trace ra file JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{output_dir}/{state['run_id']}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    return filename


# ─────────────────────────────────────────────
# 8. Manual Test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 65)
    print("Day 09 Lab — Supervisor-Worker Graph (LangGraph + Judge)")
    print("=" * 65)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Cần cấp quyền Level 3 để khắc phục P1 khẩn cấp. Quy trình là gì?",
    ]

    for query in test_queries:
        print(f"\n▶ Query: {query}")
        result = run_graph(query)
        print(f"  Route     : {result['supervisor_route']}")
        print(f"  Reason    : {result['route_reason']}")
        print(f"  Workers   : {result['workers_called']}")
        print(f"  Answer    : {result['final_answer'][:120]}...")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Judge     : score={result['judge_score']}, verdict={result['judge_verdict']}, iter={result['judge_iterations']}")
        print(f"  Latency   : {result['latency_ms']}ms")

        trace_file = save_trace(result)
        print(f"  Trace     : {trace_file}")

    print("\n✅ graph.py test complete.")