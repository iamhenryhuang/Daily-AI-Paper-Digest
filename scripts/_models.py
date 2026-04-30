"""Shared dataclasses and scoring constants."""

from __future__ import annotations

from dataclasses import dataclass, field


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
