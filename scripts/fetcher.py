"""Fetch papers from arXiv API and Hugging Face Daily Papers."""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

from _http import request_text
from _models import HFPaperSignal, Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_RSS_URL = "https://rss.arxiv.org/rss/{category}"
HF_PAPERS_URL = "https://huggingface.co/papers"


def fetch_arxiv_papers(categories: tuple[str, ...], max_results: int) -> list[Paper]:
    params = {
        "search_query": _build_arxiv_query(categories),
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API_URL}?{urllib.parse.urlencode(params)}"
    print(f"Fetching arXiv ({', '.join(categories)})...", file=sys.stderr)
    try:
        xml_text = request_text(url, headers={"User-Agent": "daily-ai-paper-agent/1.0"}, timeout=90, retries=3)
    except RuntimeError as exc:
        print(f"Warning: failed to fetch arXiv API candidates: {exc}", file=sys.stderr)
        return _fetch_arxiv_rss_papers(categories, max_results)

    seen: set[str] = set()
    papers: list[Paper] = []
    for paper in _parse_arxiv_feed(xml_text):
        paper_id = base_arxiv_id(paper.arxiv_id)
        if paper_id not in seen:
            papers.append(paper)
            seen.add(paper_id)

    return sorted(papers, key=lambda p: p.published, reverse=True)[:max_results]


def _fetch_arxiv_rss_papers(categories: tuple[str, ...], max_results: int) -> list[Paper]:
    print("Falling back to arXiv RSS feeds...", file=sys.stderr)
    seen: set[str] = set()
    papers: list[Paper] = []
    failures: list[str] = []

    for category in categories:
        url = ARXIV_RSS_URL.format(category=urllib.parse.quote(category, safe="."))
        try:
            rss_text = request_text(url, headers={"User-Agent": "daily-ai-paper-agent/1.0"}, timeout=45, retries=3)
        except RuntimeError as exc:
            failures.append(f"{category}: {_short(exc)}")
            continue

        for paper in _parse_arxiv_rss(rss_text, category):
            paper_id = base_arxiv_id(paper.arxiv_id)
            if paper_id in seen:
                continue
            papers.append(paper)
            seen.add(paper_id)

    if papers:
        if failures:
            print(f"Warning: some arXiv RSS feeds failed: {'; '.join(failures)}", file=sys.stderr)
        return sorted(papers, key=lambda p: p.published, reverse=True)[:max_results]

    failure_text = "; ".join(failures) if failures else "no RSS items found"
    raise RuntimeError(f"Failed to fetch arXiv candidates from API and RSS fallback: {failure_text}")


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


def _parse_arxiv_rss(rss_text: str, category: str) -> list[Paper]:
    root = ET.fromstring(rss_text)
    papers: list[Paper] = []

    for item in root.findall(".//item"):
        link = _normalize(_xml_text(item.find("link")))
        arxiv_id = _extract_arxiv_id(link)
        if not arxiv_id:
            continue

        raw_title = _normalize(html.unescape(_xml_text(item.find("title"))))
        title = re.sub(r"^arXiv:\d{4}\.\d{4,5}(?:v\d+)?\s*\([^)]*\):\s*", "", raw_title).strip()
        description = _normalize(html.unescape(re.sub(r"<[^>]+>", " ", _xml_text(item.find("description")))))
        authors, summary = _split_rss_description(description)
        published = _parse_rss_date(_xml_text(item.find("pubDate")))
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"

        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=title or arxiv_id,
                authors=authors,
                summary=summary,
                published=published,
                updated=published,
                categories=[category],
                abs_url=abs_url,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            )
        )

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


def _extract_arxiv_id(value: str) -> str:
    match = re.search(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", value)
    return match.group(0) if match else ""


def _split_rss_description(value: str) -> tuple[list[str], str]:
    value = _normalize(value)
    authors: list[str] = []
    summary = value

    authors_match = re.search(r"^Authors?:\s*(.*?)(?:\s+Abstract:\s*|\s*$)", value, flags=re.IGNORECASE)
    if authors_match:
        authors = [_normalize(part) for part in re.split(r",| and ", authors_match.group(1)) if _normalize(part)]

    abstract_match = re.search(r"Abstract:\s*(.*)$", value, flags=re.IGNORECASE)
    if abstract_match:
        summary = _normalize(abstract_match.group(1))

    return authors, summary


def _parse_rss_date(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = dt.datetime.now(dt.timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
