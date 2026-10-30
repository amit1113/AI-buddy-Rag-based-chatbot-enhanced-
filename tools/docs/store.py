"""Persistent vector store. Vectors and chunk metadata are saved to disk;
the FAISS index is rebuilt in memory on load. That keeps deleting a document simple."""
import json
from dataclasses import asdict
from pathlib import Path

import faiss
import numpy as np

from core import config
from .ingest import Chunk


class DocStore:
    def __init__(self, directory=config.INDEX_DIR):
        self.dir = Path(directory)
        self.chunks = []
        self.vectors = np.empty((0, 0), dtype="float32")
        self._index = None
        self._load()

    # ---- persistence ----
    def _load(self):
        meta_file = self.dir / "chunks.json"
        vec_file = self.dir / "vectors.npy"
        if meta_file.exists() and vec_file.exists():
            raw = json.loads(meta_file.read_text(encoding="utf-8"))
            self.chunks = [Chunk(**item) for item in raw]
            self.vectors = np.load(vec_file)
            self._rebuild()

    def _save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = [asdict(chunk) for chunk in self.chunks]
        (self.dir / "chunks.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        np.save(self.dir / "vectors.npy", self.vectors)

    def _rebuild(self):
        if not self.chunks:
            self._index = None
            return
        self._index = faiss.IndexFlatIP(self.vectors.shape[1])  # inner product on normalised vectors
        self._index.add(self.vectors)

    # ---- editing ----
    def _drop(self, source):
        keep = [i for i, chunk in enumerate(self.chunks) if chunk.source != source]
        if len(keep) == len(self.chunks):
            return False
        self.chunks = [self.chunks[i] for i in keep]
        self.vectors = self.vectors[keep] if keep else np.empty((0, 0), dtype="float32")
        return True

    def add(self, chunks, vectors):
        """Add chunks with their vectors. Re-adding a file replaces its old chunks."""
        if not chunks:
            return
        if self.vectors.size and vectors.shape[1] != self.vectors.shape[1]:
            raise ValueError(
                "Embedding size changed (different embedding model?). "
                "Delete data/index and re-add your documents."
            )
        for source in {chunk.source for chunk in chunks}:
            self._drop(source)
        self.chunks.extend(chunks)
        self.vectors = vectors if self.vectors.size == 0 else np.vstack([self.vectors, vectors])
        self._rebuild()
        self._save()

    def remove(self, source):
        if self._drop(source):
            self._rebuild()
            self._save()
            return True
        return False

    # ---- reading ----
    def search(self, query_vector, k):
        """Return [(Chunk, score)] best first. Score is cosine similarity (higher = closer)."""
        if self._index is None:
            return []
        k = min(k, len(self.chunks))
        scores, ids = self._index.search(query_vector.reshape(1, -1), k)
        return [(self.chunks[i], float(s)) for s, i in zip(scores[0], ids[0]) if i != -1]

    def documents(self):
        """{file name: number of chunks}"""
        counts = {}
        for chunk in self.chunks:
            counts[chunk.source] = counts.get(chunk.source, 0) + 1
        return counts
