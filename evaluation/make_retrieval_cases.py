"""Draft retrieval test questions from your own PDFs, so you don't have to write them all by hand.

    python evaluation/make_retrieval_cases.py "C:\\path\\report.pdf" --n 15

For random pages it asks the model for a question that only that page can answer, and records the
page as the right answer. REVIEW THE FILE afterwards: delete weak questions and reword a few in your
own words (generated questions tend to copy the page's wording, which makes retrieval look easier
than it is). Then save the result as evaluation/retrieval_cases.json."""
import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.docs.ingest import read_pdf_pages

SYSTEM = (
    "You write test questions for a document search system. Given one page of a document, write ONE "
    "specific question that this page answers and that someone could ask without having seen the page. "
    "Do not say 'the page', 'the passage' or 'the text'. Do not include the answer. "
    "Reply with the question only."
)


def make_cases(pdf_path, count, seed, generate, min_chars=300):
    pdf_path = Path(pdf_path)
    pages = [(number, text) for number, text in read_pdf_pages(pdf_path) if len(text) >= min_chars]
    random.Random(seed).shuffle(pages)
    cases = []
    for number, text in pages[:count]:
        question = generate(f"Page text:\n{text[:3000]}", system=SYSTEM, temperature=0.3).strip().strip('"')
        if question:
            cases.append({"file": pdf_path.name, "question": question, "pages": [number], "generated": True})
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("pdfs", nargs="+")
    parser.add_argument("--n", type=int, default=15, help="questions per PDF")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", default=str(Path(__file__).with_name("retrieval_cases.generated.json")))
    args = parser.parse_args()

    from core import llm

    cases = []
    for pdf in args.pdfs:
        made = make_cases(pdf, args.n, args.seed, llm.generate)
        print(f"{Path(pdf).name}: {len(made)} questions")
        cases += made
    Path(args.out).write_text(json.dumps(cases, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(cases)} questions to {args.out}\nNow review and edit them, then save as retrieval_cases.json")
    if len(cases) < 10:
        print("WARNING: fewer than 10 questions. Use a longer PDF (10+ pages of real text) for a meaningful evaluation.")


if __name__ == "__main__":
    main()
