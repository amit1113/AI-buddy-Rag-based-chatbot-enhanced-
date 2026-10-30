"""PDF -> page-aware chunks. No UI, no network, no embeddings: just text handling."""
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from core import config


@dataclass
class Chunk:
    text: str
    source: str  # file name, used for citations
    page: int    # 1-based page number


def read_pdf_pages(path):
    """Return [(page_number, text)] for pages that contain extractable text."""
    reader = PdfReader(str(path))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((number, text))
    return pages


def split_text(text, size, overlap):
    """Split text into ~size-character pieces with overlap, preferring to cut at
    sentence ends or spaces instead of mid-word."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")

    text = " ".join(text.split())  # collapse newlines and repeated spaces
    if len(text) <= size:
        return [text] if text else []

    pieces = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window_start = start + int(size * 0.6)  # only cut in the last 40% of the window
            cut = max(text.rfind(". ", window_start, end), text.rfind(" ", window_start, end))
            if cut != -1:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunk_pdf(path, size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP):
    """Chunk a PDF page by page so every chunk knows its file and page number."""
    path = Path(path)
    chunks = []
    for page_number, text in read_pdf_pages(path):
        for piece in split_text(text, size, overlap):
            chunks.append(Chunk(text=piece, source=path.name, page=page_number))
    return chunks
