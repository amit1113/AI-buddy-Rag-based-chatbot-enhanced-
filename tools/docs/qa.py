"""The documents tool: add PDFs, then ask questions answered from them with citations."""
from core import config, llm
from core.reply import Reply
from .ingest import chunk_pdf
from .store import DocStore

NOT_FOUND = "I couldn't find that in the documents."

SYSTEM_PROMPT = (
    "You answer questions using only the context excerpts provided. "
    "Each excerpt is labelled with its source file and page. "
    f'If the context does not contain the answer, reply exactly: "{NOT_FOUND}" '
    "After each claim, cite the excerpt like [file.pdf, p. 3]. Be concise."
)

REWRITE_SYSTEM = (
    "Rewrite the user's latest question as a single standalone search query, "
    "using the conversation for context (resolve words like 'it', 'that', 'the second one'). "
    "Reply with the query only. If the question is already standalone, repeat it unchanged."
)


def _transcript(history, limit=6):
    lines = []
    for role, text in history[-limit:]:
        label = "User" if role == "user" else "Assistant"
        lines.append(f"{label}: {text[:500]}")
    return "\n".join(lines)


class DocsTool:
    def __init__(self, store=None):
        self.store = store or DocStore()

    # ---- managing documents ----
    def add_pdf(self, path):
        """Chunk, embed and save a PDF. Returns the number of chunks added."""
        chunks = chunk_pdf(path)
        if not chunks:
            raise ValueError(
                f"No extractable text in {path}. It may be a scanned PDF, which needs OCR."
            )
        vectors = llm.embed([chunk.text for chunk in chunks], task="RETRIEVAL_DOCUMENT")
        self.store.add(chunks, vectors)
        return len(chunks)

    def remove(self, source):
        return self.store.remove(source)

    def list_documents(self):
        return self.store.documents()

    # ---- answering ----
    def retrieve(self, question, k=config.TOP_K):
        query_vector = llm.embed([question], task="RETRIEVAL_QUERY")
        return self.store.search(query_vector, k)

    def _standalone_question(self, question, history):
        """Turn a follow-up like 'what about the second one?' into a searchable question."""
        if not history:
            return question
        try:
            rewritten = llm.generate(
                f"Conversation so far:\n{_transcript(history)}\n\nLatest question: {question}",
                system=REWRITE_SYSTEM,
            ).strip()
        except Exception:
            return question  # rewriting is a bonus; never block the answer on it
        return rewritten or question

    def ask(self, question, history=None, k=config.TOP_K):
        """Return {"answer": str, "sources": [{"file", "page", "score"}]}."""
        history = history or []
        hits = self.retrieve(self._standalone_question(question, history), k)
        if not hits:
            return {"answer": "No documents have been added yet.", "sources": []}

        context = "\n\n".join(f"[{c.source}, p. {c.page}]\n{c.text}" for c, _ in hits)
        prompt = f"Context:\n{context}\n\nQuestion: {question}"
        answer = llm.generate(prompt, system=SYSTEM_PROMPT, history=history).strip()

        sources = []
        if not answer.startswith(NOT_FOUND):  # no citations for "not found" answers
            seen = set()
            for chunk, score in hits:
                key = (chunk.source, chunk.page)
                if key not in seen:
                    seen.add(key)
                    sources.append({"file": chunk.source, "page": chunk.page, "score": round(score, 3)})
        return {"answer": answer, "sources": sources}

    def run(self, question, history):
        """Tool interface used by the assistant core."""
        if not self.store.chunks:
            return Reply("No documents yet. Add one with /add <path-to-pdf>.", remember=False)
        result = self.ask(question, history=history)
        return Reply(result["answer"], sources=result["sources"])
