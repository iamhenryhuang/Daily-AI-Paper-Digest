#!/usr/bin/env python3
"""Build manifest.json for the static GitHub Pages reader."""

from __future__ import annotations

import json
import re
from pathlib import Path

ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b")


def parse_report(text: str) -> dict[str, list[dict[str, object]]]:
    """Extract the title outline (focus + also-watch papers) from a report."""
    focus: list[dict[str, object]] = []
    also: list[dict[str, object]] = []
    section = ""
    current: dict[str, object] | None = None

    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            current = None
            continue

        focus_heading = re.match(r"^###\s+\d+\.\s+(.+)$", line)
        also_heading = re.match(r"^\d+\.\s+\*\*(.+)\*\*\s*$", line)
        if section == "重點關注" and focus_heading:
            current = {"title": focus_heading.group(1).strip()}
            focus.append(current)
            continue
        if section == "也值得關注" and also_heading:
            current = {"title": also_heading.group(1).strip()}
            also.append(current)
            continue

        if current is None:
            continue
        field = re.match(r"^\s*-\s*(分數|arXiv|分類)\s*[：:]\s*(.+)$", line)
        if not field:
            continue
        key, value = field.groups()
        if key == "分數":
            current["score"] = int(value) if value.strip().isdigit() else 0
        elif key == "arXiv":
            match = ARXIV_ID_RE.search(value)
            if match:
                current["id"] = match.group(1)
        else:
            current["categories"] = [c.strip() for c in value.split(",") if c.strip()]

    return {"focus": focus, "also": also}


def main() -> int:
    site_dir = Path("docs")
    reports_dir = site_dir / "reports"
    sources_dir = site_dir / "sources"
    entries = []

    for report_path in sorted(reports_dir.glob("*.md"), reverse=True):
        date = report_path.stem
        sources_path = sources_dir / f"{date}.md"
        if not sources_path.exists():
            continue
        outline = parse_report(report_path.read_text(encoding="utf-8"))
        entries.append(
            {
                "date": date,
                "report": report_path.relative_to(site_dir).as_posix(),
                "sources": sources_path.relative_to(site_dir).as_posix(),
                **outline,
            }
        )

    (site_dir / "manifest.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"manifest.json updated with {len(entries)} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
