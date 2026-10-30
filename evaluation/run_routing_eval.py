"""How often does the router pick the right tool?  Compares three strategies on labelled questions.

    python evaluation/run_routing_eval.py            (uses the Gemini API, one call per question)
    python evaluation/run_routing_eval.py --delay 4   (slower, if you hit rate limits)
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import intent

CASES_FILE = Path(__file__).with_name("routing_cases.json")
RESULTS_DIR = Path(__file__).with_name("results")
TOOLS = ["chat", "doc", "screen"]
MODES = ["rules", "llm", "hybrid"]


def evaluate(data, generate, delay=0.0, sleep=time.sleep, progress=None, retries=0, backoff=(10, 30, 60)):
    """Run every case through every strategy. The model is called at most once per question:
    the 'llm' and 'hybrid' strategies share the answer."""
    rows = []
    for number, case in enumerate(data["cases"], start=1):
        doc_names = data.get("documents", []) if case["has_docs"] else []
        screen_app = data.get("screen_app", "") if case["has_screen"] else ""
        cache = {}

        def classify(question, candidates, names, app, last_tool, cache=cache):
            if "tool" not in cache and "error" not in cache:
                started = time.perf_counter()
                error = None
                for attempt in range(retries + 1):  # rate limits are common: wait and try again
                    try:
                        cache["tool"] = intent.classify_with_llm(question, candidates, names, app, last_tool, generate=generate)
                        error = None
                        break
                    except Exception as exc:
                        error = exc
                        if attempt < retries:
                            sleep(backoff[min(attempt, len(backoff) - 1)])
                if error is not None:
                    cache["error"] = error
                cache["seconds"] = time.perf_counter() - started
                sleep(delay)
            if "error" in cache:
                raise cache["error"]
            return cache["tool"]

        row = {"case": case, "decisions": {}}
        for mode in MODES:
            row["decisions"][mode] = intent.choose_tool(
                case["question"], has_docs=case["has_docs"], has_screen=case["has_screen"],
                doc_names=doc_names, screen_app=screen_app, last_tool=case.get("last_tool"),
                mode=mode, classify=classify,
            )
        row["llm_seconds"] = cache.get("seconds")
        row["api_error"] = str(cache["error"])[:160] if "error" in cache else None
        rows.append(row)
        if progress:
            progress(number, len(data["cases"]))
    return rows


def api_failed(decision):
    return decision.method == "fallback" and decision.reason.startswith("classifier failed")


def summarize(rows):
    """Accuracy, per-tool recall, confusion matrix and mistakes for each strategy.
    Questions whose model call failed (rate limit, busy server) are NOT scored for the strategies that
    need the model: that would measure the network, not the router."""
    summary = {}
    for mode in MODES:
        correct = failed = 0
        per_tool = {t: [0, 0] for t in TOOLS}                     # [right, total] by expected tool
        confusion = {t: {u: 0 for u in TOOLS} for t in TOOLS}     # expected -> predicted
        mistakes = []
        for row in rows:
            expected, decision = row["case"]["expected"], row["decisions"][mode]
            if mode != "rules" and api_failed(decision):
                failed += 1
                continue
            per_tool[expected][1] += 1
            confusion[expected][decision.tool] += 1
            if decision.tool == expected:
                correct += 1
                per_tool[expected][0] += 1
            else:
                mistakes.append((row["case"]["question"], expected, decision.tool, decision.method))
        scored = len(rows) - failed
        summary[mode] = {"accuracy": correct / scored if scored else 0.0, "correct": correct, "total": scored,
                         "failed": failed, "per_tool": per_tool, "confusion": confusion, "mistakes": mistakes}
    hybrid_by_rule = sum(1 for r in rows if r["decisions"]["hybrid"].method == "rule")
    timings = [r["llm_seconds"] for r in rows if r["llm_seconds"] is not None]
    errors = [r["api_error"] for r in rows if r.get("api_error")]
    summary["extra"] = {
        "hybrid_decided_by_rules": hybrid_by_rule,
        "hybrid_llm_calls": len(rows) - hybrid_by_rule,
        "avg_llm_seconds": sum(timings) / len(timings) if timings else None,
        "unusable_llm_answers": sum(1 for r in rows if r["decisions"]["llm"].reason == "classifier gave no usable answer"),
        "api_errors": len(errors),
        "first_api_error": errors[0] if errors else None,
    }
    return summary


def to_markdown(summary, total_cases):
    lines = [f"# Routing evaluation ({total_cases} questions, {datetime.now():%Y-%m-%d %H:%M})", ""]
    lines += ["| Strategy | Accuracy | Chat recall | Doc recall | Screen recall |", "|---|---|---|---|---|"]
    for mode in MODES:
        m = summary[mode]
        recall = [f"{m['per_tool'][t][0]}/{m['per_tool'][t][1]}" for t in TOOLS]
        skipped = f", {m['failed']} skipped" if m["failed"] else ""
        lines.append(f"| {mode} | {m['accuracy']:.0%} ({m['correct']}/{m['total']}{skipped}) | " + " | ".join(recall) + " |")
    e = summary["extra"]
    lines += ["", f"- Hybrid settled {e['hybrid_decided_by_rules']} questions with rules alone and needed "
                  f"{e['hybrid_llm_calls']} model calls ({e['hybrid_llm_calls'] / total_cases:.0%} of questions)."]
    if e["avg_llm_seconds"] is not None:
        lines.append(f"- Average routing call took {e['avg_llm_seconds']:.2f} s.")
    if e["unusable_llm_answers"]:
        lines.append(f"- The model answered in a form that could not be read for {e['unusable_llm_answers']} questions (counted as mistakes).")
    if e["api_errors"]:
        lines.append(f"- **{e['api_errors']} model calls failed even after retries** and are left out of the scores for 'llm' and 'hybrid'. "
                     f"First error: {e['first_api_error']}. Run again later or with a larger --delay.")
    for mode in MODES:
        lines += ["", f"## Mistakes: {mode}", ""]
        mistakes = summary[mode]["mistakes"]
        if not mistakes:
            lines.append("None.")
        for question, expected, predicted, method in mistakes:
            lines.append(f"- \"{question}\": expected {expected}, got {predicted} ({method})")
    lines += ["", "## Confusion matrix for hybrid (rows = expected, columns = predicted)", "",
              "| expected \\ predicted | " + " | ".join(TOOLS) + " |", "|---|" + "---|" * len(TOOLS)]
    for t in TOOLS:
        lines.append(f"| {t} | " + " | ".join(str(summary['hybrid']['confusion'][t][u]) for u in TOOLS) + " |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--delay", type=float, default=4.0, help="seconds to wait between model calls (avoids rate limits)")
    parser.add_argument("--retries", type=int, default=3, help="extra attempts, with growing waits, when a call fails")
    args = parser.parse_args()

    from core import llm  # imported here so tests can import this file without the SDK

    data = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    rows = evaluate(data, llm.generate, delay=args.delay, retries=args.retries,
                    progress=lambda n, total: print(f"\r  {n}/{total}", end="", flush=True))
    print()
    report = to_markdown(summarize(rows), len(rows))
    print(report)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"routing_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
