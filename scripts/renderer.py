"""Render Markdown report and sources page."""

from __future__ import annotations

import re
from pathlib import Path

from _models import HFPaperSignal, Paper, ScoreBreakdown
from fetcher import base_arxiv_id


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
        "- 來源：arXiv API + Hugging Face Daily Papers",
        f"- 分類：{', '.join(categories)}",
        f"- 摘要模型：OpenAI `{model}`",
        f"- 透明來源頁：[{sources_path.name}](../sources/{sources_path.name})",
        "",
        "## 重點關注",
        "",
    ]

    for index, paper in enumerate(focus, start=1):
        lines.extend(_render_focus_paper(index, paper, summaries[paper.arxiv_id], scores[paper.arxiv_id]))

    if also:
        lines.extend(["## 也值得關注", ""])
        for index, paper in enumerate(also, start=1):
            score = scores[paper.arxiv_id]
            lines.extend([
                f"{index}. **{paper.title}**",
                f"   - 分數：{score.total}",
                f"   - arXiv: [{paper.arxiv_id}]({paper.abs_url})",
                f"   - 發表日期：{paper.published[:10]}",
                f"   - 分類：{', '.join(paper.categories)}",
                f"   - 入選理由：{format_reasons(score)}",
                "",
            ])

    return "\n".join(lines).rstrip() + "\n"


def render_sources(
    report_date: str,
    candidates: list[Paper],
    scores: dict[str, ScoreBreakdown],
    hf_signals: dict[str, HFPaperSignal],
) -> str:
    ranked = sorted(candidates, key=lambda p: scores[p.arxiv_id].total, reverse=True)
    lines = [
        f"# 論文來源頁 - {report_date}",
        "",
        "本頁列出規則引擎檢查過的所有 arXiv 候選論文，以及每篇論文的分數理由。",
        "",
        f"- arXiv 候選論文數：{len(candidates)}",
        f"- 命中 Hugging Face Daily Papers：{sum(1 for p in candidates if base_arxiv_id(p.arxiv_id) in hf_signals)}",
        "",
        "| 分數 | 論文 | 發表日期 | 分類 | 入選理由 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for paper in ranked:
        score = scores[paper.arxiv_id]
        paper_link = f"[{_escape_md(paper.title)}]({paper.abs_url})"
        categories = _escape_md(", ".join(paper.categories))
        lines.append(f"| {score.total} | {paper_link} | {paper.published[:10]} | {categories} | {_escape_md(format_reasons(score))} |")

    return "\n".join(lines).rstrip() + "\n"


def format_reasons(score: ScoreBreakdown) -> str:
    return "; ".join(score.reasons) if score.reasons else "未命中正向訊號"


# ── private helpers ──────────────────────────────────────────────────────────

def _render_focus_paper(index: int, paper: Paper, summary: dict[str, str], score: ScoreBreakdown) -> list[str]:
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


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
