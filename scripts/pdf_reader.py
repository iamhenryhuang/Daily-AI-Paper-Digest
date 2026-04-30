"""Download PDF, extract text, and cache to disk."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

from _http import request_bytes
from _models import Paper, PaperText
from fetcher import base_arxiv_id


def load_paper_text(paper: Paper, cache_dir: Path, max_chars: int) -> PaperText:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_safe_name(base_arxiv_id(paper.arxiv_id))}.txt"

    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8")
        if cached.strip():
            return PaperText(text=_limit(cached, max_chars), source="PDF text cache")

    try:
        pdf_bytes = request_bytes(paper.pdf_url, headers={"User-Agent": "daily-ai-paper-agent/1.0"}, timeout=120, retries=3)
        text = _extract_pdf_text(pdf_bytes)
        if not text.strip():
            raise RuntimeError("PDF text extraction returned empty text")
        cache_path.write_text(text, encoding="utf-8")
        return PaperText(text=_limit(text, max_chars), source="PDF full text")
    except Exception as exc:
        print(f"Warning: failed to load PDF text for {paper.arxiv_id}: {exc}", file=sys.stderr)
        return PaperText(text=paper.summary, source=f"abstract fallback ({_short(exc)})")


# ── private helpers ──────────────────────────────────────────────────────────

def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Missing dependency: install pypdf to enable full-paper reviews") from exc

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = _clean_page(text)
        if text:
            pages.append(f"[Page {index}]\n{text}")
    return "\n\n".join(pages)


def _clean_page(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _limit(value: str, max_chars: int) -> str:
    trimmed = _trim_references(value)
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[:max_chars].rstrip() + "\n\n[全文因長度限制截斷]"


def _trim_references(value: str) -> str:
    match = re.search(r"\n\s*(references|bibliography)\s*\n", value, flags=re.IGNORECASE)
    if not match:
        return value
    main_text = value[: match.start()].rstrip()
    return main_text if len(main_text) > 4000 else value


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _short(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:180]
