#!/usr/bin/env python3
"""Fetch, score, and summarize daily AI papers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

from _http import request_text
from _models import DEFAULT_CATEGORIES, DEFAULT_FULL_TEXT_CHARS, DEFAULT_MODEL, Paper, PaperText, ScoreBreakdown
from fetcher import (
    base_arxiv_id,
    fetch_arxiv_papers,
    fetch_hf_daily_papers,
    load_reported_arxiv_ids,
    select_candidate_papers,
)
from pdf_reader import load_paper_text
from renderer import render_report, render_sources
from scorer import score_paper, select_papers

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def parse_args() -> argparse.Namespace:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    parser = argparse.ArgumentParser(description="Create a daily AI paper digest.")
    parser.add_argument("--date", default=today, help="Report date. Default: today in UTC.")
    parser.add_argument("--focus-count", type=int, default=5, help="Maximum papers in the focus section.")
    parser.add_argument("--also-count", type=int, default=3, help="Maximum papers in the also-watch section.")
    parser.add_argument("--lookback-days", type=int, default=3, help="Fallback window to inspect when the preferred paper date has no new papers.")
    parser.add_argument("--preferred-offset-days", type=int, default=1, help="Prefer papers published this many days before the report date. Default: 1 (yesterday).")
    parser.add_argument("--arxiv-results", type=int, default=120, help="How many arXiv results to inspect.")
    parser.add_argument("--focus-threshold", type=int, default=8, help="Minimum score for focus papers.")
    parser.add_argument("--also-threshold", type=int, default=4, help="Minimum score for also-watch papers.")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", DEFAULT_MODEL), help="OpenAI model name.")
    parser.add_argument("--output-dir", default="docs/reports", help="Directory for Markdown reports.")
    parser.add_argument("--sources-dir", default="docs/sources", help="Directory for transparent source pages.")
    parser.add_argument("--paper-cache-dir", default=".cache/papers", help="Directory for cached PDF text.")
    parser.add_argument("--full-text-chars", type=int, default=DEFAULT_FULL_TEXT_CHARS, help="Maximum extracted PDF characters to send to the model per focus paper.")
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


def summarize_paper(api_key: str, model: str, paper: Paper, score: ScoreBreakdown, paper_text: PaperText) -> dict[str, str]:
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

語言規則：
1. JSON key 固定使用英文：intro, motivation, method, result, conclusion, research_gap。
2. JSON value 必須使用繁體中文撰寫。
3. 專有名詞、模型名稱、資料集名稱、方法名稱、指標名稱、會議名稱可以保留英文。
4. 不要輸出完整英文句子；即使原文是英文，也要用繁體中文解釋。

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
---BEGIN PAPER TEXT---
{paper_text.text}
---END PAPER TEXT---

最終輸出提醒：只輸出 JSON object；key 用英文，所有 value 都必須是繁體中文。除了專有名詞、模型名稱、資料集名稱、方法名稱、指標名稱、會議名稱外，不要使用英文句子。
""".strip()

    raw = _call_openai(api_key, model, prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"OpenAI did not return JSON: {raw[:500]}")
        data = json.loads(match.group(0))

    expected = ("intro", "motivation", "method", "result", "conclusion", "research_gap")
    return {key: re.sub(r"\s+", " ", str(data.get(key, "摘要未明確說明。"))).strip() for key in expected}


def _call_openai(api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "input": prompt,
        "temperature": 0.2,
        "text": {"format": {"type": "json_object"}},
    }
    response_text = request_text(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
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
    candidates = select_candidate_papers(papers, report_date, args.lookback_days, args.preferred_offset_days, reported_ids)
    if not candidates:
        print("No new papers found in the preferred fallback window; using fetched papers after removing previously reported IDs.", file=sys.stderr)
        candidates = [p for p in papers if base_arxiv_id(p.arxiv_id) not in reported_ids]

    if not candidates:
        print("No new arXiv candidates found after excluding previously reported papers.", file=sys.stderr)
        return 1

    print("Fetching Hugging Face Daily Papers...", file=sys.stderr)
    hf_signals = fetch_hf_daily_papers()

    print("Scoring candidates...", file=sys.stderr)
    scores = {p.arxiv_id: score_paper(p, hf_signals) for p in candidates}
    focus, also = select_papers(candidates, scores, args.focus_threshold, args.also_threshold, args.focus_count, args.also_count, args.date)

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
    sources_path.write_text(render_sources(args.date, candidates, scores, hf_signals), encoding="utf-8")
    report_path.write_text(render_report(args.date, focus, also, summaries, scores, categories, args.model, sources_path), encoding="utf-8")
    print(report_path)
    print(sources_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
