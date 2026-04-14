"""
workers/judge.py — Judge/Evaluator Worker
Đánh giá chất lượng câu trả lời từ synthesis_worker và quyết định retry không.

Flow:
    synthesis_worker → judge_worker → [RETRY → synthesis_worker | PASS → END]

Scoring dimensions (mỗi 0.0-1.0):
    - faithfulness: Câu trả lời có grounded hoàn toàn trong context?
    - completeness: Có trả lời đủ tất cả phần của câu hỏi?
    - relevance: Có trực tiếp, súc tích, không lan man?

Verdict:
    - PASS: overall_score >= PASS_THRESHOLD  (default 0.70)
    - RETRY: overall_score < threshold VÀ còn lần retry
    - PASS (forced): đã đạt MAX_RETRIES → dừng dù score chưa đủ

Gọi độc lập để test:
    python workers/judge.py
"""

import os
import json
import re

WORKER_NAME = "judge_worker"
PASS_THRESHOLD = 0.70   # Score tối thiểu để PASS
MAX_RETRIES = 2         # Số lần synthesis được retry tối đa


JUDGE_SYSTEM_PROMPT = """Bạn là evaluator đánh giá chất lượng câu trả lời của hệ thống AI Helpdesk nội bộ.

Nhiệm vụ: Đánh giá câu trả lời theo 3 tiêu chí, trả về JSON thuần túy.

Tiêu chí đánh giá:
1. faithfulness (0.0-1.0): Câu trả lời có hoàn toàn dựa trên context cung cấp không?
   - 1.0 = mọi thông tin đều có nguồn từ context
   - 0.5 = một phần dựa trên context, một phần suy diễn
   - 0.0 = hoàn toàn bịa hoặc không liên quan đến context

2. completeness (0.0-1.0): Câu trả lời có đầy đủ không?
   - 1.0 = trả lời tất cả các phần của câu hỏi
   - 0.5 = trả lời được phần chính nhưng thiếu điều kiện/ngoại lệ
   - 0.0 = bỏ qua phần lớn câu hỏi hoặc abstain không cần thiết

3. relevance (0.0-1.0): Câu trả lời có súc tích và trực tiếp không?
   - 1.0 = trả lời thẳng vào vấn đề, không lan man
   - 0.5 = có thông tin đúng nhưng lẫn thông tin không liên quan
   - 0.0 = lạc đề hoàn toàn

Trả về JSON với format (không có markdown, chỉ JSON thuần):
{
  "faithfulness": <float>,
  "completeness": <float>,
  "relevance": <float>,
  "overall": <float, weighted: faithfulness*0.4 + completeness*0.35 + relevance*0.25>,
  "verdict": "PASS" hoặc "RETRY",
  "feedback": "<nếu RETRY: nêu cụ thể 1-2 điểm cần cải thiện; nếu PASS: chuỗi rỗng>"
}"""


def _call_llm_judge(task: str, context: str, answer: str) -> dict:
    """
    Gọi LLM để đánh giá câu trả lời.
    Returns dict với faithfulness, completeness, relevance, overall, verdict, feedback.
    """
    user_content = f"""Câu hỏi: {task}

--- Context được cung cấp cho hệ thống ---
{context[:2000]}
---

Câu trả lời của hệ thống:
{answer}

Hãy đánh giá câu trả lời theo 3 tiêu chí và trả về JSON."""

    # Option A: OpenAI
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,    # Judge phải deterministic
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception:
        pass

    # Option B: Gemini
    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-flash")
        combined = f"{JUDGE_SYSTEM_PROMPT}\n\n{user_content}"
        response = model.generate_content(combined)
        raw = response.text
        # Strip markdown nếu có
        raw = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        return json.loads(raw)
    except Exception:
        pass

    # Fallback: không thể gọi LLM → trả về PASS để không block pipeline
    return {
        "faithfulness": 0.5,
        "completeness": 0.5,
        "relevance": 0.5,
        "overall": 0.5,
        "verdict": "PASS",
        "feedback": "",
        "_fallback": True,
    }


def _build_context_summary(chunks: list) -> str:
    """Tạo context ngắn gọn từ retrieved_chunks để Judge đánh giá."""
    if not chunks:
        return "(Không có context — hệ thống không tìm được tài liệu phù hợp)"
    parts = []
    for i, chunk in enumerate(chunks[:3], 1):  # Chỉ lấy top-3 để tránh quá dài
        source = chunk.get("source", "unknown")
        text = chunk.get("text", "")[:400]
        parts.append(f"[{i}] {source}: {text}")
    return "\n".join(parts)


def evaluate(task: str, answer: str, chunks: list, judge_iterations: int) -> dict:
    """
    Đánh giá câu trả lời và trả về kết quả với verdict.

    Returns:
        {
            "judge_score": float,
            "judge_feedback": str,
            "judge_verdict": "PASS" | "RETRY",
            "judge_detail": dict,   # faithfulness, completeness, relevance
        }
    """
    context_summary = _build_context_summary(chunks)
    raw = _call_llm_judge(task, context_summary, answer)

    overall = float(raw.get("overall", 0.5))
    feedback = raw.get("feedback", "")
    verdict_from_llm = raw.get("verdict", "PASS")

    # Override verdict: PASS forced nếu đã hết retry
    if judge_iterations >= MAX_RETRIES:
        verdict = "PASS"  # force stop
        feedback = ""
    elif overall >= PASS_THRESHOLD:
        verdict = "PASS"
        feedback = ""
    else:
        verdict = "RETRY"

    return {
        "judge_score": round(overall, 3),
        "judge_feedback": feedback,
        "judge_verdict": verdict,
        "judge_detail": {
            "faithfulness": raw.get("faithfulness", 0.5),
            "completeness": raw.get("completeness", 0.5),
            "relevance": raw.get("relevance", 0.5),
            "llm_verdict": verdict_from_llm,
            "_fallback": raw.get("_fallback", False),
        },
    }


def run(state: dict) -> dict:
    """
    Worker entry point — gọi từ graph.py.
    Đọc final_answer, retrieved_chunks từ state, gọi evaluate(), cập nhật state.
    """
    task = state.get("task", "")
    answer = state.get("final_answer", "")
    chunks = state.get("retrieved_chunks", [])

    # Tăng counter mỗi lần judge chạy
    iterations = state.get("judge_iterations", 0)
    state["judge_iterations"] = iterations + 1

    state.setdefault("workers_called", [])
    state.setdefault("history", [])
    state["workers_called"].append(WORKER_NAME)

    worker_io = {
        "worker": WORKER_NAME,
        "input": {
            "task": task,
            "answer_length": len(answer),
            "judge_iteration": state["judge_iterations"],
        },
        "output": None,
        "error": None,
    }

    try:
        result = evaluate(task, answer, chunks, iterations)

        state["judge_score"] = result["judge_score"]
        state["judge_feedback"] = result["judge_feedback"]
        state["judge_verdict"] = result["judge_verdict"]

        worker_io["output"] = {
            "score": result["judge_score"],
            "verdict": result["judge_verdict"],
            "feedback": result["judge_feedback"],
            "detail": result["judge_detail"],
            "iteration": state["judge_iterations"],
        }
        state["history"].append(
            f"[{WORKER_NAME}] iteration={state['judge_iterations']}, "
            f"score={result['judge_score']:.3f}, verdict={result['judge_verdict']}"
        )

        if result["judge_verdict"] == "RETRY":
            state["history"].append(
                f"[{WORKER_NAME}] feedback='{result['judge_feedback']}' → routing to synthesis retry"
            )

    except Exception as e:
        worker_io["error"] = {"code": "JUDGE_FAILED", "reason": str(e)}
        # Fail-safe: PASS để không block pipeline
        state["judge_score"] = 0.5
        state["judge_feedback"] = ""
        state["judge_verdict"] = "PASS"
        state["history"].append(f"[{WORKER_NAME}] ERROR (fail-safe PASS): {e}")

    state.setdefault("worker_io_logs", []).append(worker_io)
    return state


# ─────────────────────────────────────────────
# Test độc lập
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("Judge Worker — Standalone Test")
    print("=" * 55)

    test_state = {
        "task": "SLA ticket P1 là bao lâu?",
        "final_answer": "Ticket P1 có SLA phản hồi ban đầu 15 phút. Thời gian xử lý 4 giờ. [sla_p1_2026.txt]",
        "retrieved_chunks": [
            {
                "text": "Ticket P1: Phản hồi ban đầu 15 phút. Xử lý 4 giờ. Escalation tự động sau 10 phút không có phản hồi.",
                "source": "sla_p1_2026.txt",
                "score": 0.92,
            }
        ],
        "judge_iterations": 0,
    }

    result = run(test_state.copy())
    print(f"\nScore     : {result['judge_score']}")
    print(f"Verdict   : {result['judge_verdict']}")
    print(f"Feedback  : {result['judge_feedback']}")
    print(f"Iterations: {result['judge_iterations']}")

    print("\n--- Test 2: Low quality answer (should RETRY) ---")
    test_state2 = {
        "task": "Contractor cần Admin Access Level 3 để fix P1. Quy trình cấp quyền tạm thời?",
        "final_answer": "Bạn cần liên hệ IT để được cấp quyền.",  # Low quality — thiếu detail
        "retrieved_chunks": [
            {
                "text": "Level 3 Admin Access yêu cầu approval từ Line Manager, IT Admin và IT Security. Emergency bypass không áp dụng cho Level 3.",
                "source": "access_control_sop.txt",
                "score": 0.85,
            }
        ],
        "judge_iterations": 0,
    }
    result2 = run(test_state2.copy())
    print(f"\nScore     : {result2['judge_score']}")
    print(f"Verdict   : {result2['judge_verdict']}")
    print(f"Feedback  : {result2['judge_feedback']}")

    print("\n✅ judge_worker test done.")