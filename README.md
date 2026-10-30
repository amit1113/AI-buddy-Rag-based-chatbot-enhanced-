# AI Buddy

A one-click desktop assistant: direct chat, questions about your documents, and questions about whatever is on your screen.

## Setup

```
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # then add your Gemini API key
```

## Status

- [x] Step 1: documents tool (page-aware chunks, persistent FAISS index, citations)
- [x] Step 2: core (chat memory, router, retry + fallback model) + terminal chat: `python cli.py`
- [x] Step 3a: screen tool, active-window screenshot (Windows)
- [ ] Step 3b: selection/clipboard and browser page text
- [x] Step 4: overlay UI + global hotkey: `python buddy.py` (Windows), with a scrollable conversation; the screen is captured only when a question needs it
- [x] Step 5: automatic routing (rules + LLM) and evaluation scripts in `evaluation/`
- [ ] Step 6: polish and demo

## Evaluation

```
python evaluation/run_routing_eval.py
python evaluation/make_retrieval_cases.py "C:\path\report.pdf" --n 15
python evaluation/run_retrieval_eval.py "C:\path\report.pdf" --cases evaluation/retrieval_cases.json
```

Reports are saved in `evaluation/results/`. Paste your own numbers here once you have run them.
