"""Does document search find the right page? Compares chunk sizes on your own PDFs.

    python evaluation/run_retrieval_eval.py "C:\\path\\report.pdf" --cases evaluation/retrieval_cases.json
    python evaluation/run_retrieval_eval.py a.pdf b.pdf --sizes 400,800,1500 --k 1,3,5

Each case is {"file": "report.pdf", "question": "...", "pages": [3]}. A search counts as a hit when one
of the top-k chunks comes from the right file and one of the right pages. Reports hit rate at k and MRR
(mean reciprocal rank: 1.0 means the right chunk is always first). Uses a temporary index, so your real
documents in data/ are untouched."""
import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.docs.ingest import chunk_pdf
from tools.docs.store import DocStore

RESULTS_DIR = Path(__file__).with_name("results")


def evaluate_retrieval(pdf_paths, cases, sizes, ks, embed):
    """embed(texts, task) -> normalised vectors. Returns one result dict per chunk size."""
    top = max(ks)
    query_vectors = embed([c["question"] for c in cases], task="RETRIEVAL_QUERY")
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for size in sizes:
            overlap = max(20, size // 7)
            chunks = []
            for path in pdf_paths:
                chunks += chunk_pdf(path, size=size, overlap=overlap)
            store = DocStore(Path(tmp) / f"size_{size}")
            store.add(chunks, embed([c.text for c in chunks], task="RETRIEVAL_DOCUMENT"))

            hits = {k: 0 for k in ks}
            reciprocal = 0.0
            for case, vector in zip(cases, query_vectors):
                found = store.search(vector, top)
                rank = next(
                    (i for i, (chunk, _) in enumerate(found)
                     if chunk.source == case["file"] and chunk.page in case["pages"]),
                    None,
                )
                if rank is not None:
                    reciprocal += 1 / (rank + 1)
                    for k in ks:
                        if rank < k:
                            hits[k] += 1
            n = len(cases)
            results.append({"size": size, "overlap": overlap, "chunks": len(chunks),
                            "hit": {k: hits[k] / n for k in ks}, "mrr": reciprocal / n})
    return results


def to_markdown(results, ks, n_cases):
    lines = [f"# Retrieval evaluation ({n_cases} questions, {datetime.now():%Y-%m-%d %H:%M})", "",
             "| Chunk size | Overlap | Chunks | " + " | ".join(f"Hit@{k}" for k in ks) + " | MRR |",
             "|---|---|---|" + "---|" * len(ks) + "---|"]
    for r in results:
        lines.append(f"| {r['size']} | {r['overlap']} | {r['chunks']} | "
                     + " | ".join(f"{r['hit'][k]:.0%}" for k in ks) + f" | {r['mrr']:.2f} |")
    best = max(results, key=lambda r: (r["hit"][ks[len(ks) // 2]], r["mrr"]))
    lines += ["", f"Best chunk size by Hit@{ks[len(ks) // 2]}: {best['size']} characters."]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("pdfs", nargs="+")
    parser.add_argument("--cases", default=str(Path(__file__).with_name("retrieval_cases.json")))
    parser.add_argument("--sizes", default="400,800,1500")
    parser.add_argument("--k", default="1,3,5")
    args = parser.parse_args()

    from core import llm

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    names = {Path(p).name for p in args.pdfs}
    cases = [c for c in cases if c["file"] in names]
    if not cases:
        sys.exit("No cases match the PDFs you passed (the 'file' field must equal the PDF's file name).")
    if len(cases) < 10:
        print(f"WARNING: only {len(cases)} questions, so the numbers below are not meaningful. "
              "Use a longer PDF and at least 20 questions.")
    sizes = [int(x) for x in args.sizes.split(",")]
    ks = sorted(int(x) for x in args.k.split(","))
    print(f"{len(cases)} questions, chunk sizes {sizes}")
    report = to_markdown(evaluate_retrieval(args.pdfs, cases, sizes, ks, llm.embed), ks, len(cases))
    print(report)
    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"retrieval_{datetime.now():%Y%m%d_%H%M%S}.md"
    out.write_text(report, encoding="utf-8")
    print(f"Saved to {out}")


if __name__ == "__main__":
    main()
