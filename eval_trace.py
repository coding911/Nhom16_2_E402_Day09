"""
eval_trace.py — Trace Evaluation & Comparison
Sprint 4: Chạy pipeline với test questions, phân tích trace, so sánh single vs multi.

Chạy:
    python eval_trace.py                  # Chạy 15 test questions
    python eval_trace.py --grading        # Chạy grading questions (sau 17:00)
    python eval_trace.py --analyze        # Phân tích trace đã có
    python eval_trace.py --compare        # So sánh single vs multi

Outputs:
    artifacts/traces/          — trace của từng câu hỏi
    artifacts/grading_run.jsonl — log câu hỏi chấm điểm
    artifacts/eval_report.json  — báo cáo tổng kết
"""

import json
import os
import sys
import argparse
from datetime import datetime
from typing import Optional

# Import graph
sys.path.insert(0, os.path.dirname(__file__))
from graph import run_graph, save_trace


# ─────────────────────────────────────────────
# 1. Run Pipeline on Test Questions
# ─────────────────────────────────────────────

def run_test_questions(questions_file: str = "data/test_questions.json") -> list:
    """
    Chạy pipeline với danh sách câu hỏi, lưu trace từng câu.

    Returns:
        list of (question, result) tuples
    """
    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    print(f"\n📋 Running {len(questions)} test questions from {questions_file}")
    print("=" * 60)

    results = []
    for i, q in enumerate(questions, 1):
        question_text = q["question"]
        q_id = q.get("id", f"q{i:02d}")

        print(f"[{i:02d}/{len(questions)}] {q_id}: {question_text[:65]}...")

        try:
            result = run_graph(question_text)
            result["question_id"] = q_id

            # Save individual trace
            save_trace(result, f"artifacts/traces")
            print(f"  ✓ route={result.get('supervisor_route', '?')}, "
                  f"conf={result.get('confidence', 0):.2f}, "
                  f"{result.get('latency_ms', 0)}ms")

            results.append({
                "id": q_id,
                "question": question_text,
                "expected_answer": q.get("expected_answer", ""),
                "expected_sources": q.get("expected_sources", []),
                "difficulty": q.get("difficulty", "unknown"),
                "category": q.get("category", "unknown"),
                "result": result,
            })

        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            results.append({
                "id": q_id,
                "question": question_text,
                "error": str(e),
                "result": None,
            })

    print(f"\n✅ Done. {sum(1 for r in results if r.get('result'))} / {len(results)} succeeded.")
    return results


# ─────────────────────────────────────────────
# 2. Run Grading Questions (Sprint 4)
# ─────────────────────────────────────────────

def run_grading_questions(questions_file: str = "data/grading_questions.json") -> str:
    """
    Chạy pipeline với grading questions và lưu JSONL log.
    Dùng cho chấm điểm nhóm (chạy sau khi grading_questions.json được public lúc 17:00).

    Returns:
        path tới grading_run.jsonl
    """
    if not os.path.exists(questions_file):
        print(f"❌ {questions_file} chưa được public (sau 17:00 mới có).")
        return ""

    with open(questions_file, encoding="utf-8") as f:
        questions = json.load(f)

    os.makedirs("artifacts", exist_ok=True)
    output_file = "artifacts/grading_run.jsonl"

    print(f"\n🎯 Running GRADING questions — {len(questions)} câu")
    print(f"   Output → {output_file}")
    print("=" * 60)

    with open(output_file, "w", encoding="utf-8") as out:
        for i, q in enumerate(questions, 1):
            q_id = q.get("id", f"gq{i:02d}")
            question_text = q["question"]
            print(f"[{i:02d}/{len(questions)}] {q_id}: {question_text[:65]}...")

            try:
                result = run_graph(question_text)
                record = {
                    "id": q_id,
                    "question": question_text,
                    "answer": result.get("final_answer", "PIPELINE_ERROR: no answer"),
                    "sources": result.get("retrieved_sources", []),
                    "supervisor_route": result.get("supervisor_route", ""),
                    "route_reason": result.get("route_reason", ""),
                    "workers_called": result.get("workers_called", []),
                    "mcp_tools_used": [t.get("tool") for t in result.get("mcp_tools_used", [])],
                    "confidence": result.get("confidence", 0.0),
                    "hitl_triggered": result.get("hitl_triggered", False),
                    "judge_score": result.get("judge_score", 0.0),
                    "judge_verdict": result.get("judge_verdict", ""),
                    "judge_iterations": result.get("judge_iterations", 0),
                    "latency_ms": result.get("latency_ms"),
                    "timestamp": datetime.now().isoformat(),
                }
                print(f"  ✓ route={record['supervisor_route']}, conf={record['confidence']:.2f}, "
                      f"judge={record['judge_score']:.2f}/{record['judge_verdict']}")
            except Exception as e:
                record = {
                    "id": q_id,
                    "question": question_text,
                    "answer": f"PIPELINE_ERROR: {e}",
                    "sources": [],
                    "supervisor_route": "error",
                    "route_reason": str(e),
                    "workers_called": [],
                    "mcp_tools_used": [],
                    "confidence": 0.0,
                    "hitl_triggered": False,
                    "judge_score": 0.0,
                    "judge_verdict": "error",
                    "judge_iterations": 0,
                    "latency_ms": None,
                    "timestamp": datetime.now().isoformat(),
                }
                print(f"  ✗ ERROR: {e}")

            out.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"\n✅ Grading log saved → {output_file}")
    return output_file


# ─────────────────────────────────────────────
# 3. Analyze Traces
# ─────────────────────────────────────────────

def analyze_traces(traces_dir: str = "artifacts/traces") -> dict:
    """
    Đọc tất cả trace files và tính metrics tổng hợp.

    Metrics:
    - routing_distribution: % câu đi vào mỗi worker
    - avg_confidence: confidence trung bình
    - avg_latency_ms: latency trung bình
    - mcp_usage_rate: % câu có MCP tool call
    - hitl_rate: % câu trigger HITL
    - source_coverage: các tài liệu nào được dùng nhiều nhất

    Returns:
        dict of metrics
    """
    if not os.path.exists(traces_dir):
        print(f"⚠️  {traces_dir} không tồn tại. Chạy run_test_questions() trước.")
        return {}

    trace_files = [f for f in os.listdir(traces_dir) if f.endswith(".json")]
    if not trace_files:
        print(f"⚠️  Không có trace files trong {traces_dir}.")
        return {}

    traces = []
    for fname in trace_files:
        with open(os.path.join(traces_dir, fname)) as f:
            traces.append(json.load(f))

    # Compute metrics
    routing_counts = {}
    confidences = []
    latencies = []
    mcp_calls = 0
    hitl_triggers = 0
    source_counts = {}
    judge_scores = []
    judge_retries = 0   # Số câu bị judge RETRY ít nhất 1 lần
    judge_pass_first = 0  # Số câu PASS ngay lần đầu (iter=1)

    for t in traces:
        route = t.get("supervisor_route", "unknown")
        routing_counts[route] = routing_counts.get(route, 0) + 1

        conf = t.get("confidence", 0)
        if conf:
            confidences.append(conf)

        lat = t.get("latency_ms")
        if lat:
            latencies.append(lat)

        if t.get("mcp_tools_used"):
            mcp_calls += 1

        if t.get("hitl_triggered"):
            hitl_triggers += 1

        for src in t.get("retrieved_sources", []):
            source_counts[src] = source_counts.get(src, 0) + 1

        # Judge metrics
        js = t.get("judge_score", 0)
        if js:
            judge_scores.append(js)
        ji = t.get("judge_iterations", 0)
        if ji > 1:
            judge_retries += 1
        elif ji == 1:
            judge_pass_first += 1

    total = len(traces)
    metrics = {
        "total_traces": total,
        "routing_distribution": {k: f"{v}/{total} ({100*v//total}%)" for k, v in routing_counts.items()},
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 0,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "mcp_usage_rate": f"{mcp_calls}/{total} ({100*mcp_calls//total}%)" if total else "0%",
        "hitl_rate": f"{hitl_triggers}/{total} ({100*hitl_triggers//total}%)" if total else "0%",
        "top_sources": sorted(source_counts.items(), key=lambda x: -x[1])[:5],
        # Judge metrics
        "avg_judge_score": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else 0,
        "judge_pass_first_try": f"{judge_pass_first}/{total}",
        "judge_retry_rate": f"{judge_retries}/{total} ({100*judge_retries//total}%)" if total else "0%",
    }

    return metrics


# ─────────────────────────────────────────────
# 4. Compare Single vs Multi Agent
# ─────────────────────────────────────────────

def compare_single_vs_multi(
    multi_traces_dir: str = "artifacts/traces",
    day08_results_file: Optional[str] = None,
) -> dict:
    """
    So sánh Day 08 (single agent RAG) vs Day 09 (multi-agent).

    TODO Sprint 4: Điền kết quả thực tế từ Day 08 vào day08_baseline.

    Returns:
        dict của comparison metrics
    """
    multi_metrics = analyze_traces(multi_traces_dir)

    # Day 08 baseline — từ evaluation_report.json, 3 config, 10 câu, thang 0-5
    # Raw scores (0-1 scale × 5): Dense / Hybrid / Hybrid+Rerank
    day08_baseline = {
        "total_questions": 10,
        "configs": {
            "dense": {
                "faithfulness": 1.45,       # 0.291 × 5
                "answer_relevance": 1.65,   # 0.329 × 5
                "context_recall": 1.00,     # 0.195 × 5 ≈ 1.00
                "completeness": 2.15,       # 0.428 × 5
                "latency_s": 4.74,
            },
            "hybrid": {
                "faithfulness": 1.45,       # 0.288 × 5
                "answer_relevance": 2.30,   # 0.465 × 5
                "context_recall": 1.00,     # 0.195 × 5
                "completeness": 2.90,       # 0.583 × 5
                "latency_s": 8.94,
            },
            "hybrid_rerank": {              # Best config
                "faithfulness": 1.50,       # 0.296 × 5
                "answer_relevance": 2.65,   # 0.533 × 5
                "context_recall": 1.00,     # 0.195 × 5
                "completeness": 3.10,       # 0.617 × 5
                "latency_s": 9.47,
            },
        },
        "best_config": "hybrid_rerank",
        "hallucination_cases": 1,           # gq02: ERR-403 hallucinate quy trình
        "abstain_rate": "10%",              # 1/10 câu abstain đúng (gq07)
        "multi_hop_accuracy": "N/A",        # Day 08 không có multi-hop test cases
        "routing_visibility": False,
        "mcp_tools": False,
        "hitl": False,
        "score_scale": "/5.00",
    }

    if day08_results_file and os.path.exists(day08_results_file):
        with open(day08_results_file) as f:
            day08_baseline = json.load(f)

    d09_conf = multi_metrics.get("avg_confidence", 0)
    comparison = {
        "generated_at": datetime.now().isoformat(),
        "day08_single_agent": day08_baseline,
        "day09_multi_agent": multi_metrics,
        "analysis": {
            "routing_visibility": (
                "Day 09 ghi route_reason + workers_called cho từng câu → "
                "debug rõ ràng từng bước. Day 08 không có trace."
            ),
            "faithfulness": (
                "Day 08 best config (Hybrid+Rerank) faithfulness = 1.50/5 (30%). "
                f"Day 09 confidence avg = {d09_conf:.3f} (thang khác — cosine similarity, không so sánh trực tiếp). "
                "Day 08 Dense/Hybrid faithfulness = 1.45/5 (29%)."
            ),
            "completeness_gap": (
                "Day 08 completeness: Dense=2.15/5, Hybrid=2.90/5, Hybrid+Rerank=3.10/5 (62%). "
                "Day 09 có policy_tool_worker + MCP check_access_permission → xử lý exception tốt hơn (ước tính +10%). "
                "Day 08 bị penalty gq02 (hallucinate) và zero gq05 (thiếu coverage)."
            ),
            "latency_delta": (
                "Day 08 Hybrid+Rerank latency = 9.47s/câu (reranking overhead). "
                "Day 09 warm avg ~3.0s/câu (15 câu, không có reranking step). "
                "Day 09 nhanh hơn Day 08 best config dù có 2-3 worker hops."
            ),
            "debuggability": (
                "Multi-agent: test từng worker độc lập, xem route_reason và worker_io_logs. "
                "Single-agent: phải trace toàn bộ code, không có signal nào để bắt đầu."
            ),
            "mcp_benefit": (
                "Day 09 gọi MCP check_access_permission và get_ticket_info qua dispatch_tool — "
                "không cần hard-code. Day 08 không có capability này. "
                f"MCP usage rate: {multi_metrics.get('mcp_usage_rate', 'N/A')}."
            ),
            "hitl": (
                f"Day 09 HITL rate: {multi_metrics.get('hitl_rate', 'N/A')}. "
                "Day 08 không có HITL — ERR-403-AUTH trả lời sai (hallucinate process) thay vì abstain."
            ),
            "judge_loop": (
                f"Day 09 có Judge Worker (LLM-as-Judge): avg score={multi_metrics.get('avg_judge_score', 'N/A')}, "
                f"retry rate={multi_metrics.get('judge_retry_rate', 'N/A')}, "
                f"pass first try={multi_metrics.get('judge_pass_first_try', 'N/A')}. "
                "Day 08 không có self-evaluation — answer được dùng trực tiếp dù chất lượng thấp."
            ),
        },
    }

    return comparison


# ─────────────────────────────────────────────
# 5. Save Eval Report
# ─────────────────────────────────────────────

def save_eval_report(comparison: dict) -> str:
    """Lưu báo cáo eval tổng kết ra file JSON."""
    os.makedirs("artifacts", exist_ok=True)
    output_file = "artifacts/eval_report.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)
    return output_file


# ─────────────────────────────────────────────
# 6. CLI Entry Point
# ─────────────────────────────────────────────

def print_metrics(metrics: dict):
    """Print metrics đẹp."""
    if not metrics:
        return
    print("\n📊 Trace Analysis:")
    for k, v in metrics.items():
        if isinstance(v, list):
            print(f"  {k}:")
            for item in v:
                print(f"    • {item}")
        elif isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Day 09 Lab — Trace Evaluation")
    parser.add_argument("--grading", action="store_true", help="Run grading questions")
    parser.add_argument("--analyze", action="store_true", help="Analyze existing traces")
    parser.add_argument("--compare", action="store_true", help="Compare single vs multi")
    parser.add_argument("--test-file", default="data/test_questions.json", help="Test questions file")
    args = parser.parse_args()

    if args.grading:
        # Chạy grading questions
        log_file = run_grading_questions()
        if log_file:
            print(f"\n✅ Grading log: {log_file}")
            print("   Nộp file này trước 18:00!")

    elif args.analyze:
        # Phân tích traces
        metrics = analyze_traces()
        print_metrics(metrics)

    elif args.compare:
        # So sánh single vs multi
        comparison = compare_single_vs_multi()
        report_file = save_eval_report(comparison)
        print(f"\n📊 Comparison report saved → {report_file}")
        print("\n=== Day 08 vs Day 09 ===")
        for k, v in comparison.get("analysis", {}).items():
            print(f"  {k}: {v}")

    else:
        # Default: chạy test questions
        results = run_test_questions(args.test_file)

        # Phân tích trace
        metrics = analyze_traces()
        print_metrics(metrics)

        # Lưu báo cáo
        comparison = compare_single_vs_multi()
        report_file = save_eval_report(comparison)
        print(f"\n📄 Eval report → {report_file}")
        print("\n✅ Sprint 4 complete!")
        print("   Next: Điền docs/ templates và viết reports/")
