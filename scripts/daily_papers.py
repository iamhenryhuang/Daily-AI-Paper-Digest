#!/usr/bin/env python3
"""Fetch, score, and summarize daily AI papers."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import io
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


ARXIV_API_URL = "https://export.arxiv.org/api/query"
HF_PAPERS_URL = "https://huggingface.co/papers"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_CATEGORIES = ("cs.AI", "cs.CL", "cs.LG", "cs.CV", "cs.MA", "cs.IR")
DEFAULT_PAPER_CACHE_DIR = ".cache/papers"
DEFAULT_FULL_TEXT_CHARS = 120_000

TOP_INSTITUTIONS = (
    "google",
    "deepmind",
    "openai",
    "anthropic",
    "meta",
    "facebook ai",
    "microsoft",
    "nvidia",
    "apple",
    "amazon",
    "stanford",
    "mit",
    "massachusetts institute of technology",
    "berkeley",
    "uc berkeley",
    "carnegie mellon",
    "cmu",
    "princeton",
    "harvard",
    "cornell",
    "oxford",
    "cambridge",
    "eth zurich",
    "epfl",
    "university of toronto",
    "mila",
    "ucsd",
    "ucla",
    "uiuc",
    "university of washington",
    "tsinghua",
    "peking university",
    "shanghai ai laboratory",
    "zhejiang university",
    "fudan",
    "ustc",
    "huawei",
    "bytedance",
    "alibaba",
    "tencent",
    "baidu",
    "salesforce",
    "ibm",
)

TOP_VENUES = (
    "neurips",
    "nips",
    "iclr",
    "icml",
    "acl",
    "emnlp",
    "naacl",
    "cvpr",
    "iccv",
    "eccv",
    "aaai",
    "ijcai",
    "kdd",
    "sigir",
    "www",
    "the web conference",
    "colm",
)

CODE_KEYWORDS = ("github.com", "code is available", "source code", "open-source", "open source", "repository")

@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    title: str
    authors: list[str]
    summary: str
    published: str
    updated: str
    categories: list[str]
    abs_url: str
    pdf_url: str
    comment: str = ""
    journal_ref: str = ""
    doi: str = ""


@dataclass
class HFPaperSignal:
    arxiv_id: str
    title: str = ""
    votes: int = 0
    url: str = ""


@dataclass
class ScoreBreakdown:
    total: int = 0
    reasons: list[str] = field(default_factory=list)
    hf_votes: int = 0


@dataclass(frozen=True)
class PaperText:
    text: str
    source: str


def parse_args() -> argparse.Namespace:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    parser = argparse.ArgumentParser(description="Create a daily AI paper digest.")
    parser.add_argument("--date", default=today, help="Report date. Default: today in UTC.")
    parser.add_argument("--focus-count", type=int, default=5, help="Maximum papers in the focus section.")
    parser.add_argument("--also-count", type=int, default=3, help="Maximum papers in the also-watch section.")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=3,
        help="Fallback window to inspect when the preferred paper date has no new papers.",
    )
    parser.add_argument(
        "--preferred-offset-days",
        type=int,
        default=1,
        help="Prefer papers published this many days before the report date. Default: 1 (yesterday).",
    )
    parser.add_argument("--arxiv-results", type=int, default=120, help="How many arXiv results to inspect.")
    parser.add_argument("--focus-threshold", type=int, default=8, help="Minimum score for focus papers.")
    parser.add_argument("--also-threshold", type=int, default=4, help="Minimum score for also-watch papers.")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL), help="OpenAI model name.")
    parser.add_argument("--output-dir", default="docs/reports", help="Directory for Markdown reports.")
    parser.add_argument("--sources-dir", default="docs/sources", help="Directory for transparent source pages.")
    parser.add_argument("--paper-cache-dir", default=DEFAULT_PAPER_CACHE_DIR, help="Directory for cached PDF text.")
    parser.add_argument(
        "--full-text-chars",
        type=int,
        default=DEFAULT_FULL_TEXT_CHARS,
        help="Maximum extracted PDF characters to send to the model per focus paper.",
    )
    return parser.parse_args()


def load_env_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env_categories() -> tuple[str, ...]:
    raw = os.getenv("ARXIV_CATEGORIES", "")
    categories = tuple(item.strip() for item in raw.split(",") if item.strip())
    return categories or DEFAULT_CATEGORIES


def build_arxiv_query(categories: tuple[str, ...]) -> str:
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    ai_terms = (
        'all:"artificial intelligence" OR all:"large language model" OR '
        'all:"machine learning" OR all:"deep learning" OR all:"agent" OR all:"retrieval"'
    )
    return f"({category_query}) AND ({ai_terms})"


def request_text(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    retries: int = 3,
) -> str:
    request = urllib.request.Request(url, data=data, headers=headers or {})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:800]}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt == retries:
                raise RuntimeError(f"Network error calling {url}: {exc}") from exc
            last_error = exc

        wait_seconds = min(30, 2 ** attempt)
        print(f"Request failed, retrying in {wait_seconds}s ({attempt}/{retries}): {last_error}", file=sys.stderr)
        time.sleep(wait_seconds)

    raise RuntimeError(f"Network error calling {url}: {last_error}")


def request_bytes(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
    retries: int = 3,
) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise RuntimeError(f"HTTP {exc.code} from {url}: {body[:800]}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            if attempt == retries:
                raise RuntimeError(f"Network error calling {url}: {exc}") from exc
            last_error = exc

        wait_seconds = min(30, 2 ** attempt)
        print(f"Request failed, retrying in {wait_seconds}s ({attempt}/{retries}): {last_error}", file=sys.stderr)
        time.sleep(wait_seconds)

    raise RuntimeError(f"Network error calling {url}: {last_error}")


def fetch_arxiv_papers(categories: tuple[str, ...], max_results: int) -> list[Paper]:
    per_category = max(10, (max_results + len(categories) - 1) // len(categories))
    papers: list[Paper] = []
    seen: set[str] = set()
    errors: list[str] = []

    for index, category in enumerate(categories, start=1):
        params = {
            "search_query": build_arxiv_query((category,)),
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
            errors.append(f"{category}: {short_error(exc)}")
            print(f"Warning: failed to fetch arXiv category {category}: {exc}", file=sys.stderr)
            continue

        for paper in parse_arxiv_feed(xml_text):
            paper_id = base_arxiv_id(paper.arxiv_id)
            if paper_id not in seen:
                papers.append(paper)
                seen.add(paper_id)

        if index < len(categories):
            time.sleep(3)

    if not papers:
        raise RuntimeError("Failed to fetch arXiv candidates. " + " | ".join(errors))

    return sorted(papers, key=lambda paper: paper.published, reverse=True)[:max_results]


def parse_arxiv_feed(xml_text: str) -> list[Paper]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []

    for entry in root.findall("atom:entry", ns):
        abs_url = text(entry.find("atom:id", ns))
        arxiv_id = abs_url.rstrip("/").split("/")[-1]
        title = normalize_space(text(entry.find("atom:title", ns)))
        summary = normalize_space(text(entry.find("atom:summary", ns)))
        published = text(entry.find("atom:published", ns))
        updated = text(entry.find("atom:updated", ns))
        authors = [normalize_space(text(author.find("atom:name", ns))) for author in entry.findall("atom:author", ns)]
        categories = [node.attrib.get("term", "") for node in entry.findall("atom:category", ns) if node.attrib.get("term")]
        comment = normalize_space(text(entry.find("arxiv:comment", ns)))
        journal_ref = normalize_space(text(entry.find("arxiv:journal_ref", ns)))
        doi = normalize_space(text(entry.find("arxiv:doi", ns)))
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href", "")
                break
        papers.append(
            Paper(
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
            )
        )
    return papers


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
        title = extract_hf_title(chunk)
        votes = extract_hf_votes(chunk)
        current = signals.get(arxiv_id)
        if current is None or votes > current.votes:
            signals[arxiv_id] = HFPaperSignal(
                arxiv_id=arxiv_id,
                title=title,
                votes=votes,
                url=f"{HF_PAPERS_URL}/{arxiv_id}",
            )
    return signals


def extract_hf_title(chunk: str) -> str:
    title_patterns = (
        r"<h3[^>]*>(.*?)</h3>",
        r"<h2[^>]*>(.*?)</h2>",
        r'title="([^"]+)"',
    )
    for pattern in title_patterns:
        match = re.search(pattern, chunk, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return strip_tags(match.group(1))
    return ""


def extract_hf_votes(chunk: str) -> int:
    vote_patterns = (
        r"(\d{1,5})\s*</[^>]+>\s*</[^>]+>\s*<[^>]+>\s*Submitted",
        r"(\d{1,5})\s*(?:likes|votes|upvotes)",
        r"aria-label=\"(\d{1,5})\s*(?:likes|votes|upvotes)",
    )
    for pattern in vote_patterns:
        match = re.search(pattern, chunk, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return 0


def strip_tags(value: str) -> str:
    return normalize_space(re.sub(r"<[^>]+>", " ", html.unescape(value)))


def text(node: ET.Element | None) -> str:
    return "" if node is None or node.text is None else html.unescape(node.text)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def base_arxiv_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


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


def recent_papers(papers: list[Paper], report_date: dt.date, lookback_days: int) -> list[Paper]:
    earliest = report_date - dt.timedelta(days=lookback_days)
    selected = []
    seen: set[str] = set()

    for paper in papers:
        published_date = parse_arxiv_date(paper.published)
        paper_id = base_arxiv_id(paper.arxiv_id)
        if paper_id in seen:
            continue
        if earliest <= published_date <= report_date:
            selected.append(paper)
            seen.add(paper_id)
    return selected


def load_reported_arxiv_ids(*directories: Path, exclude_date: str | None = None) -> set[str]:
    reported: set[str] = set()
    for directory in directories:
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


def parse_arxiv_date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def score_papers(papers: list[Paper], hf_signals: dict[str, HFPaperSignal]) -> dict[str, ScoreBreakdown]:
    return {paper.arxiv_id: score_paper(paper, hf_signals) for paper in papers}


def score_paper(paper: Paper, hf_signals: dict[str, HFPaperSignal]) -> ScoreBreakdown:
    score = ScoreBreakdown()
    haystack = " ".join(
        [
            paper.title,
            paper.summary,
            paper.comment,
            paper.journal_ref,
            " ".join(paper.categories),
        ]
    ).lower()

    matched_institutions = sorted({name for name in TOP_INSTITUTIONS if name in haystack})
    if matched_institutions:
        add(score, 2, "提及頂級機構：" + ", ".join(matched_institutions[:3]))

    hf_signal = hf_signals.get(base_arxiv_id(paper.arxiv_id))
    if hf_signal:
        score.hf_votes = hf_signal.votes
        add(score, 3, "收錄於 Hugging Face Daily Papers")
        vote_score = hf_vote_score(hf_signal.votes)
        if vote_score:
            add(score, vote_score, f"Hugging Face 票數：{hf_signal.votes}")

    matched_venues = sorted({venue for venue in TOP_VENUES if venue in haystack})
    if matched_venues:
        add(score, 3, "提及頂級會議：" + ", ".join(matched_venues[:2]))

    if any(keyword in haystack for keyword in CODE_KEYWORDS):
        add(score, 2, "提及程式碼可用")

    return score


def add(score: ScoreBreakdown, points: int, reason: str) -> None:
    score.total += points
    score.reasons.append(f"+{points} {reason}")


def hf_vote_score(votes: int) -> int:
    if votes >= 100:
        return 4
    if votes >= 50:
        return 3
    if votes >= 20:
        return 2
    if votes >= 1:
        return 1
    return 0


def short_error(exc: Exception) -> str:
    return normalize_space(str(exc))[:180]


def select_papers(
    papers: list[Paper],
    scores: dict[str, ScoreBreakdown],
    focus_threshold: int,
    also_threshold: int,
    focus_count: int,
    also_count: int,
    random_seed: str,
) -> tuple[list[Paper], list[Paper]]:
    ranked = rank_papers_by_score(papers, scores, random_seed)
    focus = [paper for paper in ranked if scores[paper.arxiv_id].total >= focus_threshold][:focus_count]
    focus_ids = {paper.arxiv_id for paper in focus}
    also = [
        paper
        for paper in ranked
        if paper.arxiv_id not in focus_ids and scores[paper.arxiv_id].total >= also_threshold
    ][:also_count]

    if not focus:
        focus = ranked[:focus_count]
        focus_ids = {paper.arxiv_id for paper in focus}
        also = [paper for paper in ranked if paper.arxiv_id not in focus_ids][:also_count]

    return focus, also


def rank_papers_by_score(
    papers: list[Paper],
    scores: dict[str, ScoreBreakdown],
    random_seed: str,
) -> list[Paper]:
    rng = random.Random(random_seed)
    groups: dict[int, list[Paper]] = {}
    for paper in papers:
        groups.setdefault(scores[paper.arxiv_id].total, []).append(paper)

    ranked: list[Paper] = []
    for score in sorted(groups.keys(), reverse=True):
        tied = groups[score]
        rng.shuffle(tied)
        ranked.extend(tied)
    return ranked


def load_paper_text(paper: Paper, cache_dir: Path, max_chars: int) -> PaperText:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{safe_cache_name(base_arxiv_id(paper.arxiv_id))}.txt"
    if cache_path.exists():
        cached = cache_path.read_text(encoding="utf-8")
        if cached.strip():
            return PaperText(text=limit_full_text(cached, max_chars), source="PDF text cache")

    try:
        pdf_bytes = request_bytes(
            paper.pdf_url,
            headers={"User-Agent": "daily-ai-paper-agent/1.0"},
            timeout=120,
            retries=3,
        )
        text_content = extract_pdf_text(pdf_bytes)
        if not text_content.strip():
            raise RuntimeError("PDF text extraction returned empty text")
        cache_path.write_text(text_content, encoding="utf-8")
        return PaperText(text=limit_full_text(text_content, max_chars), source="PDF full text")
    except Exception as exc:
        print(f"Warning: failed to load PDF text for {paper.arxiv_id}: {exc}", file=sys.stderr)
        return PaperText(text=paper.summary, source=f"abstract fallback ({short_error(exc)})")


def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Missing dependency: install pypdf to enable full-paper reviews") from exc

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text_content = page.extract_text() or ""
        text_content = clean_pdf_page_text(text_content)
        if text_content:
            pages.append(f"[Page {index}]\n{text_content}")
    return "\n\n".join(pages)


def clean_pdf_page_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def limit_full_text(value: str, max_chars: int) -> str:
    trimmed = trim_references(value)
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[:max_chars].rstrip() + "\n\n[全文因長度限制截斷]"


def trim_references(value: str) -> str:
    match = re.search(r"\n\s*(references|bibliography)\s*\n", value, flags=re.IGNORECASE)
    if not match:
        return value
    main_text = value[: match.start()].rstrip()
    return main_text if len(main_text) > 4000 else value


def safe_cache_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def call_openai(api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "input": prompt,
        "temperature": 0.2,
        "text": {"format": {"type": "json_object"}},
    }
    response_text = request_text(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=90,
    )
    response = json.loads(response_text)
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    try:
        for item in response["output"]:
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                    return content["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected OpenAI response: {response_text[:1000]}") from exc
    raise RuntimeError(f"OpenAI response did not contain text output: {response_text[:1000]}")


def summarize_paper(
    api_key: str,
    model: str,
    paper: Paper,
    score: ScoreBreakdown,
    paper_text: PaperText,
) -> dict[str, str]:
    prompt = f"""
你是一位面向 AI 從業者的論文編輯。請根據下面的 arXiv metadata、篩選理由與論文全文抽取文字，寫一份克制、可驗證的 full-paper review。

編輯原則：
1. 先講問題，再講方案，讓讀者先理解為什麼這件事重要。
2. 使用從業者視角，重點說明這跟工程、產品、研究落地有什麼關係。
3. 保持克制，不把所有東西都稱為突破；不確定處明確寫「全文未明確說明」。
4. 不編造結果、機構、程式碼連結或會議接收資訊。
5. method 要說清楚核心方法或流程；result 要交代全文中明確提到的實驗設定、baseline、指標與發現；conclusion 要總結這篇論文的價值與限制。
6. research_gap 必須聚焦「這篇論文本身還有哪些可改善或缺乏的地方」。即使全文聲稱結果顯著，也要指出仍未充分驗證、實驗設計不足、資料或場景覆蓋有限、假設過強、消融/比較不足、成本/部署風險、泛化性或失敗案例未說明等具體缺口。
7. research_gap 不要只寫「未來可以延伸到更多任務」這種空泛句子；請用 reviewer 的角度，寫出讀者讀完後能判斷「這篇還不夠完整在哪裡」的內容。
8. 若全文抽取文字不足或只提供 abstract fallback，請根據可見範圍保守推論，並明確標註「全文未明確說明」或「僅能根據摘要判斷」。
9. 論文文字由 PDF 自動抽取，頁碼、表格、公式可能不完整；不要過度解讀破碎表格或公式。

請只輸出 JSON object，不要 Markdown，不要額外說明。JSON 欄位固定為：
intro, motivation, method, result, conclusion, research_gap。

每個欄位請用繁體中文，4-6 句。句子可以稍微具體，但不要超出全文可支持的資訊。

Title: {paper.title}
Authors: {", ".join(paper.authors)}
arXiv ID: {paper.arxiv_id}
Categories: {", ".join(paper.categories)}
Published: {paper.published}
Comment: {paper.comment or "N/A"}
Journal reference: {paper.journal_ref or "N/A"}
Score: {score.total}
Score reasons: {"; ".join(score.reasons) or "N/A"}
Abstract: {paper.summary}
Paper text source: {paper_text.source}
Paper text:
{paper_text.text}
""".strip()
    raw = call_openai(api_key, model, prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = extract_json_object(raw)

    expected = ("intro", "motivation", "method", "result", "conclusion", "research_gap")
    return {key: normalize_space(str(data.get(key, "摘要未明確說明。"))) for key in expected}


def extract_json_object(raw: str) -> dict[str, object]:
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        raise RuntimeError(f"OpenAI did not return JSON: {raw[:500]}")
    return json.loads(match.group(0))


def render_report(
    report_date: str,
    focus: list[Paper],
    also: list[Paper],
    summaries: dict[str, dict[str, str]],
    scores: dict[str, ScoreBreakdown],
    categories: tuple[str, ...],
    model: str,
    sources_path: Path,
) -> str:
    lines = [
        f"# 每日 AI 論文簡報 - {report_date}",
        "",
        f"- 來源：arXiv API + Hugging Face Daily Papers",
        f"- 分類：{', '.join(categories)}",
        f"- 摘要模型：OpenAI `{model}`",
        f"- 透明來源頁：[{sources_path.name}](../sources/{sources_path.name})",
        "",
        "## 重點關注",
        "",
    ]

    for index, paper in enumerate(focus, start=1):
        lines.extend(render_paper_summary(index, paper, summaries[paper.arxiv_id], scores[paper.arxiv_id]))

    if also:
        lines.extend(["## 也值得關注", ""])
        for index, paper in enumerate(also, start=1):
            score = scores[paper.arxiv_id]
            lines.extend(
                [
                    f"{index}. **{paper.title}**",
                    f"   - 分數：{score.total}",
                    f"   - arXiv: [{paper.arxiv_id}]({paper.abs_url})",
                    f"   - 發表日期：{paper.published[:10]}",
                    f"   - 分類：{', '.join(paper.categories)}",
                    f"   - 入選理由：{format_reasons(score)}",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def render_paper_summary(index: int, paper: Paper, summary: dict[str, str], score: ScoreBreakdown) -> list[str]:
    return [
        f"### {index}. {paper.title}",
        "",
        f"- 分數：{score.total}",
        f"- arXiv: [{paper.arxiv_id}]({paper.abs_url})",
        f"- 發表日期：{paper.published[:10]}",
        f"- 分類：{', '.join(paper.categories)}",
        f"- 入選理由：{format_reasons(score)}",
        "",
        f"**Intro:** {summary['intro']}",
        "",
        f"**Motivation:** {summary['motivation']}",
        "",
        f"**Method:** {summary['method']}",
        "",
        f"**Result:** {summary['result']}",
        "",
        f"**Conclusion:** {summary['conclusion']}",
        "",
        f"**Research Gap:** {summary['research_gap']}",
        "",
    ]


def render_sources(
    report_date: str,
    candidates: list[Paper],
    focus: list[Paper],
    also: list[Paper],
    scores: dict[str, ScoreBreakdown],
    hf_signals: dict[str, HFPaperSignal],
) -> str:
    ranked = sorted(candidates, key=lambda paper: scores[paper.arxiv_id].total, reverse=True)
    lines = [
        f"# 論文來源頁 - {report_date}",
        "",
        "本頁列出規則引擎檢查過的所有 arXiv 候選論文，以及每篇論文的分數理由。",
        "",
        f"- arXiv 候選論文數：{len(candidates)}",
        f"- 命中 Hugging Face Daily Papers：{sum(1 for paper in candidates if base_arxiv_id(paper.arxiv_id) in hf_signals)}",
        "",
        "| 分數 | 論文 | 發表日期 | 分類 | 入選理由 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for paper in ranked:
        score = scores[paper.arxiv_id]
        paper_link = f"[{escape_md(paper.title)}]({paper.abs_url})"
        categories = escape_md(", ".join(paper.categories))
        lines.append(
            f"| {score.total} | {paper_link} | {paper.published[:10]} | {categories} | {escape_md(format_reasons(score))} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def format_reasons(score: ScoreBreakdown) -> str:
    return "; ".join(score.reasons) if score.reasons else "未命中正向訊號"


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    load_env_file()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY is required.", file=sys.stderr)
        return 2

    report_date = dt.date.fromisoformat(args.date)
    categories = env_categories()
    output_dir = Path(args.output_dir)
    sources_dir = Path(args.sources_dir)
    reported_ids = load_reported_arxiv_ids(output_dir, sources_dir, exclude_date=args.date)

    print("Fetching arXiv candidates...", file=sys.stderr)
    papers = fetch_arxiv_papers(categories, args.arxiv_results)
    candidates = select_candidate_papers(
        papers,
        report_date,
        args.lookback_days,
        args.preferred_offset_days,
        reported_ids,
    )
    if not candidates:
        print(
            "No new papers found in the preferred fallback window; "
            "using fetched papers after removing previously reported IDs.",
            file=sys.stderr,
        )
        candidates = [paper for paper in papers if base_arxiv_id(paper.arxiv_id) not in reported_ids]

    if not candidates:
        print("No new arXiv candidates found after excluding previously reported papers.", file=sys.stderr)
        return 1

    print("Fetching Hugging Face Daily Papers...", file=sys.stderr)
    hf_signals = fetch_hf_daily_papers()

    print("Scoring candidates...", file=sys.stderr)
    scores = score_papers(candidates, hf_signals)
    focus, also = select_papers(
        candidates,
        scores,
        args.focus_threshold,
        args.also_threshold,
        args.focus_count,
        args.also_count,
        args.date,
    )

    summaries: dict[str, dict[str, str]] = {}
    paper_cache_dir = Path(args.paper_cache_dir)
    for index, paper in enumerate(focus, start=1):
        print(f"Summarizing {index}/{len(focus)}: {paper.title}", file=sys.stderr)
        paper_text = load_paper_text(paper, paper_cache_dir, args.full_text_chars)
        summaries[paper.arxiv_id] = summarize_paper(api_key, args.model, paper, scores[paper.arxiv_id], paper_text)
        if index < len(focus):
            time.sleep(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / f"{args.date}.md"
    sources_path = sources_dir / f"{args.date}.md"
    sources_path.write_text(render_sources(args.date, candidates, focus, also, scores, hf_signals), encoding="utf-8")
    report_path.write_text(
        render_report(args.date, focus, also, summaries, scores, categories, args.model, sources_path),
        encoding="utf-8",
    )
    print(report_path)
    print(sources_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
