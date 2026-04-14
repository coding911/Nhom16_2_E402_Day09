# Báo Cáo Cá Nhân — Lab Day 09: Multi-Agent Orchestration

**Họ và tên:** Hoàng Ngọc Thạch - 2A202600068 
**Vai trò trong nhóm:** Eval Owner (Sprint 4)  
**Ngày nộp:** 14/04/2026  
**Độ dài yêu cầu:** 500–800 từ

---

## 1. Tôi phụ trách phần nào?

Tôi chịu trách nhiệm toàn bộ **evaluation** của hệ thống — Sprint 4: file `eval_trace.py`. Cụ thể tôi implement 4 hàm chính: `run_test_questions()` (chạy pipeline với 15 test questions, lưu trace từng câu), `run_grading_questions()` (tạo `grading_run.jsonl` để nộp), `analyze_traces()` (đọc toàn bộ trace files, tính routing distribution / confidence / latency / MCP / HITL / judge metrics), và `compare_single_vs_multi()` (so sánh Day 08 single-agent vs Day 09 multi-agent).

**Module/file tôi chịu trách nhiệm:**
- File chính: `eval_trace.py`
- Functions tôi implement: `run_test_questions()`, `run_grading_questions()`, `analyze_traces()`, `compare_single_vs_multi()`, `save_eval_report()`

**Cách công việc của tôi kết nối với phần của thành viên khác:**

`eval_trace.py` gọi `run_graph()` và `save_trace()` từ `graph.py`. Khi judge_worker (workers/judge.py) ghi `judge_score`, `judge_verdict`, `judge_iterations` vào AgentState, `analyze_traces()` của tôi đọc và tổng hợp thành `avg_judge_score`, `judge_retry_rate`. Nếu field name thay đổi ở judge_worker, code của tôi sẽ báo `0` thay vì lỗi rõ — phụ thuộc ngầm này cần chú ý khi đổi contract.

**Bằng chứng:** commit `591f86df6d0529ee5ece7b280231ee8a338f3e56`, `b2f6102b2d6c92bd5e8031ad46992d5afbd4a453`.

---

## 2. Tôi đã ra một quyết định kỹ thuật gì?

**Quyết định:** Tích hợp judge metrics (`avg_judge_score`, `judge_pass_first_try`, `judge_retry_rate`) trực tiếp vào `analyze_traces()` thay vì tạo hàm phân tích riêng `analyze_judge_metrics()`.

Lựa chọn thay thế: tách hàm riêng. Tôi chọn tích hợp chung vì: (1) `analyze_traces()` đã đọc từng trace file một lần trong vòng lặp — tách ra buộc đọc lại toàn bộ file, lãng phí I/O; (2) judge metrics cùng scope với routing/confidence metrics (đều là per-trace), không phải per-worker; (3) caller của `analyze_traces()` — bao gồm `compare_single_vs_multi()` và CLI `--analyze` — nhận một dict duy nhất, dễ forward sang `analysis["judge_loop"]`.

**Trade-off đã chấp nhận:** hàm `analyze_traces()` dài hơn (~60 dòng). Nhưng cohesion cao hơn — một lần pass qua traces là đủ toàn bộ metrics.

**Bằng chứng từ code:**

```python
# eval_trace.py — analyze_traces()
judge_scores = []
judge_retries = 0
judge_pass_first = 0

for t in traces:
    js = t.get("judge_score", 0)
    if js:
        judge_scores.append(js)
    ji = t.get("judge_iterations", 0)
    if ji > 1:
        judge_retries += 1
    elif ji == 1:
        judge_pass_first += 1

metrics = {
    ...
    "avg_judge_score": round(sum(judge_scores) / len(judge_scores), 3) if judge_scores else 0,
    "judge_pass_first_try": f"{judge_pass_first}/{total}",
    "judge_retry_rate": f"{judge_retries}/{total} ({100*judge_retries//total}%)" if total else "0%",
}
```

Kết quả từ `python eval_trace.py --analyze` với 27 traces: `avg_judge_score: 0.992`, `judge_retry_rate: 0/30 (0%)`.

---

## 3. Tôi đã sửa một lỗi gì?

**Lỗi:** `run_grading_questions()` thiếu 3 judge fields trong JSONL output sau khi `judge_worker` được tích hợp vào pipeline.

**Symptom:** Chạy `python eval_trace.py --grading`, log in ra `judge=0.00/` (verdict rỗng) dù pipeline thực sự đã chạy judge_worker và trả về `judge_score`, `judge_verdict` trong AgentState. File `grading_run.jsonl` được tạo ra nhưng thiếu hoàn toàn 3 fields: `judge_score`, `judge_verdict`, `judge_iterations`.

**Root cause:** `record` dict trong `run_grading_questions()` được viết trước khi `judge_worker` được thêm vào `graph.py`. Khi graph được cập nhật để có thêm judge node, hàm `run_grading_questions()` không được cập nhật theo, 3 field mới trong AgentState không được extract ra JSONL. `result.get("judge_score")` trả về `None` thay vì `0.0` vì key chưa có trong dict cũ.

**Cách sửa:** Thêm 3 dòng vào `record` dict và cập nhật print statement:

```python
# Trước — thiếu judge fields
record = {
    "id": q_id,
    "answer": result.get("final_answer", ""),
    "confidence": result.get("confidence", 0.0),
    ...  # không có judge_score, judge_verdict, judge_iterations
}
print(f"  ✓ route={record['supervisor_route']}, conf={record['confidence']:.2f}")

# Sau — có đủ judge fields
record = {
    ...
    "judge_score":      result.get("judge_score", 0.0),
    "judge_verdict":    result.get("judge_verdict", ""),
    "judge_iterations": result.get("judge_iterations", 0),
    ...
}
print(f"  ✓ route={record['supervisor_route']}, conf={record['confidence']:.2f}, "
      f"judge={record['judge_score']:.2f}/{record['judge_verdict']}")
```

**Bằng chứng trước/sau:**

- Trước: JSONL record thiếu 3 fields — nếu nộp file này, auto-grader không đọc được judge quality metrics.
- Sau: `grading_run.jsonl` mỗi dòng có đủ 13 fields, log in `judge=0.98/PASS` xác nhận judge đã chạy đúng.

---

## 4. Tôi tự đánh giá đóng góp của mình

**Tôi làm tốt nhất ở điểm nào?**

Thiết kế `analyze_traces()` đủ linh hoạt để extend: khi judge_worker được thêm vào sau, tôi chỉ cần thêm ~10 dòng vào vòng lặp có sẵn, không phải refactor. `grading_run.jsonl` ghi đủ 13 fields theo đúng format yêu cầu — bao gồm `judge_score`, `judge_verdict`, `judge_iterations` phục vụ chấm điểm tự động.

**Tôi làm chưa tốt hoặc còn yếu ở điểm nào?**

`eval_report.json` trên disk vẫn chứa analysis cũ cho đến khi chạy lại `--compare`. Tôi chưa có validation step để phát hiện mismatch giữa code và generated report — phải đọc thủ công mới thấy sai số liệu Day 08.

**Nhóm phụ thuộc vào tôi ở đâu?**

`grading_run.jsonl` là file nộp cuối cùng để chấm điểm. Nếu `run_grading_questions()` có lỗi format JSONL, toàn bộ điểm tự động sẽ bị ảnh hưởng.

**Phần tôi phụ thuộc vào thành viên khác:**

Cần `judge_worker` ghi đúng 3 field (`judge_score`, `judge_verdict`, `judge_iterations`) vào AgentState. Cần `graph.py` export `run_graph()` và `save_trace()` đúng signature.

---

## 5. Nếu có thêm 2 giờ, tôi sẽ làm gì?

Tôi sẽ thêm **`judge_feedback` vào `grading_run.jsonl`** để audit câu nào bị RETRY và lý do cụ thể. Hiện tại log ghi `judge_score` và `judge_verdict` nhưng không ghi `judge_feedback` — khi review kết quả chấm, không biết synthesis đã cải thiện điểm gì hay chỉ PASS do đạt threshold. Trace của câu q13 (Level 3 access) cho thấy feedback "thiếu số lượng approvers và no-emergency-bypass clause" — thông tin này bị mất sau khi synthesis reset `state["judge_feedback"] = ""`, trong khi nó chính xác là bằng chứng chất lượng nhất để verify answer đã được improve.
