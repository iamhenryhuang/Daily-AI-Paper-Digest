"""Score and rank candidate papers."""

from __future__ import annotations

import random

from _models import (
    CODE_KEYWORDS,
    TOP_INSTITUTIONS,
    TOP_VENUES,
    HFPaperSignal,
    Paper,
    ScoreBreakdown,
)
from fetcher import base_arxiv_id


def score_paper(paper: Paper, hf_signals: dict[str, HFPaperSignal]) -> ScoreBreakdown:
    score = ScoreBreakdown()
    haystack = " ".join([paper.title, paper.summary, paper.comment, paper.journal_ref, " ".join(paper.categories)]).lower()

    matched_institutions = sorted({name for name in TOP_INSTITUTIONS if name in haystack})
    if matched_institutions:
        _add(score, 2, "提及頂級機構：" + ", ".join(matched_institutions[:3]))

    hf_signal = hf_signals.get(base_arxiv_id(paper.arxiv_id))
    if hf_signal:
        score.hf_votes = hf_signal.votes
        _add(score, 3, "收錄於 Hugging Face Daily Papers")
        vote_score = _hf_vote_score(hf_signal.votes)
        if vote_score:
            _add(score, vote_score, f"Hugging Face 票數：{hf_signal.votes}")

    matched_venues = sorted({venue for venue in TOP_VENUES if venue in haystack})
    if matched_venues:
        _add(score, 3, "提及頂級會議：" + ", ".join(matched_venues[:2]))

    if any(keyword in haystack for keyword in CODE_KEYWORDS):
        _add(score, 2, "提及程式碼可用")

    return score


def select_papers(
    papers: list[Paper],
    scores: dict[str, ScoreBreakdown],
    focus_threshold: int,
    also_threshold: int,
    focus_count: int,
    also_count: int,
    random_seed: str,
) -> tuple[list[Paper], list[Paper]]:
    ranked = _rank_by_score(papers, scores, random_seed)
    focus = [p for p in ranked if scores[p.arxiv_id].total >= focus_threshold][:focus_count]
    focus_ids = {p.arxiv_id for p in focus}
    also = [p for p in ranked if p.arxiv_id not in focus_ids and scores[p.arxiv_id].total >= also_threshold][:also_count]

    if not focus:
        focus = ranked[:focus_count]
        focus_ids = {p.arxiv_id for p in focus}
        also = [p for p in ranked if p.arxiv_id not in focus_ids][:also_count]

    return focus, also


# ── private helpers ──────────────────────────────────────────────────────────

def _rank_by_score(papers: list[Paper], scores: dict[str, ScoreBreakdown], random_seed: str) -> list[Paper]:
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


def _add(score: ScoreBreakdown, points: int, reason: str) -> None:
    score.total += points
    score.reasons.append(f"+{points} {reason}")


def _hf_vote_score(votes: int) -> int:
    if votes >= 100:
        return 4
    if votes >= 50:
        return 3
    if votes >= 20:
        return 2
    if votes >= 1:
        return 1
    return 0
