"""LLM-based reranking for candidate papers."""

from __future__ import annotations

import json
import re

from _http import request_text
from _models import Paper, ScoreBreakdown

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def rerank_papers(
    api_key: str,
    model: str,
    papers: list[Paper],
    scores: dict[str, ScoreBreakdown],
    preference_text: str = "",
) -> list[str]:
    """Return arXiv IDs ordered by LLM reading value."""
    if len(papers) <= 1:
        return [paper.arxiv_id for paper in papers]

    prompt = _build_prompt(papers, scores, preference_text)
    raw = _call_openai(api_key, model, prompt)
    data = _parse_json_object(raw)
    ranked = data.get("ranked_papers", [])
    if not isinstance(ranked, list):
        raise RuntimeError(f"OpenAI reranker returned invalid ranked_papers: {raw[:500]}")

    known_ids = {paper.arxiv_id for paper in papers}
    base_ids = {_base_arxiv_id(paper.arxiv_id): paper.arxiv_id for paper in papers}
    ordered: list[str] = []

    for item in ranked:
        if not isinstance(item, dict):
            continue
        paper_id = str(item.get("arxiv_id", "")).strip()
        paper_id = base_ids.get(_base_arxiv_id(paper_id), paper_id)
        if paper_id not in known_ids or paper_id in ordered:
            continue

        score = scores[paper_id]
        score.llm_rank = len(ordered) + 1
        score.llm_score = _bounded_int(item.get("score"), 1, 10)
        score.llm_reason = _clean_reason(item.get("reason", ""))
        ordered.append(paper_id)

    if not ordered:
        raise RuntimeError(f"OpenAI reranker did not return any known arXiv IDs: {raw[:500]}")

    return ordered


def apply_rerank_order(base_ranked: list[Paper], reranked_ids: list[str]) -> list[Paper]:
    by_id = {paper.arxiv_id: paper for paper in base_ranked}
    selected = [by_id[paper_id] for paper_id in reranked_ids if paper_id in by_id]
    selected_ids = {paper.arxiv_id for paper in selected}
    return selected + [paper for paper in base_ranked if paper.arxiv_id not in selected_ids]


def _build_prompt(papers: list[Paper], scores: dict[str, ScoreBreakdown], preference_text: str) -> str:
    items = []
    for index, paper in enumerate(papers, start=1):
        score = scores[paper.arxiv_id]
        items.append(
            {
                "index": index,
                "arxiv_id": paper.arxiv_id,
                "title": paper.title,
                "authors": paper.authors[:12],
                "categories": paper.categories,
                "published": paper.published[:10],
                "comment": paper.comment,
                "journal_ref": paper.journal_ref,
                "rule_score": score.total,
                "rule_reasons": score.reasons,
                "abstract": paper.summary[:2500],
            }
        )

    preferences = preference_text.strip() or (
        "No explicit user preference file was provided. Prefer papers with clear novelty, "
        "practical value, credible evidence, and strong long-term research signal."
    )
    return f"""
You are reranking candidate AI research papers for a daily digest.

Goal:
- Pick papers that are genuinely worth reading, not merely papers from famous labs or papers with social hype.
- Balance novelty, practical usefulness, research impact, methodological credibility, and fit to the user's preferences.
- Penalize vague abstracts, incremental work with unclear evidence, and papers whose importance is mostly institutional prestige.
- It is fine to keep a high rule-scored paper near the top, but only when the abstract supports it.

User preferences:
{preferences}

Return only a JSON object with this exact shape:
{{
  "ranked_papers": [
    {{
      "arxiv_id": "2601.12345v1",
      "score": 1-10,
      "reason": "one concise reason for the ranking"
    }}
  ]
}}

Include every candidate exactly once if possible. Use arXiv IDs from the input.

Candidates:
{json.dumps(items, ensure_ascii=False, indent=2)}
""".strip()


def _call_openai(api_key: str, model: str, prompt: str) -> str:
    payload = {
        "model": model,
        "input": prompt,
        "temperature": 0.1,
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


def _parse_json_object(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise RuntimeError(f"OpenAI did not return JSON: {raw[:500]}")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise RuntimeError(f"OpenAI did not return a JSON object: {raw[:500]}")
    return data


def _bounded_int(value: object, minimum: int, maximum: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, number))


def _clean_reason(value: object) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()[:220]


def _base_arxiv_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)
