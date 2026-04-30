"""Fetch papers from arXiv API and Hugging Face Daily Papers."""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

from _http import request_text
from _models import HFPaperSignal, Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
HF_PAPERS_URL = "https://huggingface.co/papers"


def fetch_arxiv_papers(categories: tuple[str, ...], max_results: int) -> list[Paper]:
    per_category = max(10, (max_results + len(categories) - 1) // len(categories))
    papers: list[Paper] = []
    seen: set[str] = set()
    errors: list[str] = []

    for index, category in enumerate(categories, start=1):
        params = {
            "search_query": _build_arxiv_query((category,)),
            "start": "0",
            "max_results": str(per_category),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
        print(f"Fetching arXiv category {index}/{len(categories)}: {category}", file=sys.stderr)
        try:
            xml_text = request_text(url, headers={"User-Agent": "daily-ai-paper-agent/1.0"}, timeout=90, retries=4)
        except RuntimeError as exc:
            errors.append(f"{category}: {_short(exc)}")
            print(f"Warning: failed to fetch arXiv category {category}: {exc}", file=sys.stderr)
            continue

        for paper in _parse_arxiv_feed(xml_text):
            paper_id = base_arxiv_id(paper.arxiv_id)
            if paper_id not in seen:
                papers.append(paper)
                seen.add(paper_id)

        if index < len(categories):
            time.sleep(3)

    if not papers:
        raise RuntimeError("Failed to fetch arXiv candidates. " + " | ".join(errors))

    return sorted(papers, key=lambda p: p.published, reverse=True)[:max_results]


def fetch_hf_daily_papers() -> dict[str, HFPaperSignal]:
    try:
        html_text = request_text(HF_PAPERS_URL, headers={"User-Agent": "daily-ai-paper-agent/1.0"}, timeout=30)
    except RuntimeError as exc:
        print(f"Warning: failed to fetch Hugging Face Daily Papers: {exc}", file=sys.stderr)
        return {}

    signals: dict[str, HFPaperSignal] = {}
    for match in re.finditer(r'href="/papers/(\d{4}\.\d{4,5})(?:v\d+)?"', html_text):
        arxiv_id = match.group(1)
        start = max(0, match.start() - 1600)
        end = min(len(html_text), match.end() + 1600)
        chunk = html.unescape(html_text[start:end])
        title = _extract_hf_title(chunk)
        votes = _extract_hf_votes(chunk)
        current = signals.get(arxiv_id)
        if current is None or votes > current.votes:
            signals[arxiv_id] = HFPaperSignal(
                arxiv_id=arxiv_id,
                title=title,
                votes=votes,
                url=f"{HF_PAPERS_URL}/{arxiv_id}",
            )
    return signals


def select_candidate_papers(
    papers: list[Paper],
    report_date: dt.date,
    lookback_days: int,
    preferred_offset_days: int,
    reported_ids: set[str] | None = None,
) -> list[Paper]:
    preferred_date = report_date - dt.timedelta(days=preferred_offset_days)
    earliest = preferred_date - dt.timedelta(days=max(0, lookback_days - 1))
    reported_ids = reported_ids or set()
    by_date: dict[dt.date, list[Paper]] = {}
    seen: set[str] = set()

    for paper in papers:
        paper_id = base_arxiv_id(paper.arxiv_id)
        if paper_id in seen or paper_id in reported_ids:
            continue
        published_date = parse_arxiv_date(paper.published)
        if earliest <= published_date <= preferred_date:
            by_date.setdefault(published_date, []).append(paper)
            seen.add(paper_id)

    if by_date.get(preferred_date):
        print(f"Using papers published on preferred date {preferred_date}.", file=sys.stderr)
        return by_date[preferred_date]

    for published_date in sorted(by_date.keys(), reverse=True):
        print(
            f"No new papers found for preferred date {preferred_date}; "
            f"falling back to {published_date}.",
            file=sys.stderr,
        )
        return by_date[published_date]

    return []


def load_reported_arxiv_ids(*directories, exclude_date: str | None = None) -> set[str]:
    reported: set[str] = set()
    for directory in directories:
        directory = Path(directory)
        if not directory.exists():
            continue
        for path in directory.glob("*.md"):
            if exclude_date and path.stem == exclude_date:
                continue
            try:
                text_value = path.read_text(encoding="utf-8")
            except OSError as exc:
                print(f"Warning: failed to read {path}: {exc}", file=sys.stderr)
                continue
            for match in re.finditer(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", text_value):
                reported.add(base_arxiv_id(match.group(0)))
    return reported


def base_arxiv_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def parse_arxiv_date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()


# ── private helpers ──────────────────────────────────────────────────────────

def _build_arxiv_query(categories: tuple[str, ...]) -> str:
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    ai_terms = (
        'all:"artificial intelligence" OR all:"large language model" OR '
        'all:"machine learning" OR all:"deep learning" OR all:"agent" OR all:"retrieval"'
    )
    return f"({category_query}) AND ({ai_terms})"


def _parse_arxiv_feed(xml_text: str) -> list[Paper]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []

    for entry in root.findall("atom:entry", ns):
        abs_url = _xml_text(entry.find("atom:id", ns))
        arxiv_id = abs_url.rstrip("/").split("/")[-1]
        title = _normalize(html.unescape(_xml_text(entry.find("atom:title", ns))))
        summary = _normalize(html.unescape(_xml_text(entry.find("atom:summary", ns))))
        published = _xml_text(entry.find("atom:published", ns))
        updated = _xml_text(entry.find("atom:updated", ns))
        authors = [_normalize(html.unescape(_xml_text(a.find("atom:name", ns)))) for a in entry.findall("atom:author", ns)]
        categories = [n.attrib.get("term", "") for n in entry.findall("atom:category", ns) if n.attrib.get("term")]
        comment = _normalize(html.unescape(_xml_text(entry.find("arxiv:comment", ns))))
        journal_ref = _normalize(html.unescape(_xml_text(entry.find("arxiv:journal_ref", ns))))
        doi = _normalize(html.unescape(_xml_text(entry.find("arxiv:doi", ns))))
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        papers.append(Paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            summary=summary,
            published=published,
            updated=updated,
            categories=categories,
            abs_url=abs_url,
            pdf_url=pdf_url or abs_url.replace("/abs/", "/pdf/"),
            comment=comment,
            journal_ref=journal_ref,
            doi=doi,
        ))
    return papers


def _extract_hf_title(chunk: str) -> str:
    for pattern in (r"<h3[^>]*>(.*?)</h3>", r"<h2[^>]*>(.*?)</h2>", r'title="([^"]+)"'):
        match = re.search(pattern, chunk, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return _normalize(re.sub(r"<[^>]+>", " ", html.unescape(match.group(1))))
    return ""


def _extract_hf_votes(chunk: str) -> int:
    for pattern in (
        r"(\d{1,5})\s*</[^>]+>\s*</[^>]+>\s*<[^>]+>\s*Submitted",
        r"(\d{1,5})\s*(?:likes|votes|upvotes)",
        r"aria-label=\"(\d{1,5})\s*(?:likes|votes|upvotes)",
    ):
        match = re.search(pattern, chunk, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0


def _xml_text(node: ET.Element | None) -> str:
    return "" if node is None or node.text is None else node.text


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _short(exc: Exception) -> str:
    return _normalize(str(exc))[:180]
