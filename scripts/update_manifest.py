#!/usr/bin/env python3
"""Build manifest.json for the static GitHub Pages reader."""

from __future__ import annotations

import json
from pathlib import Path


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
        entries.append(
            {
                "date": date,
                "report": report_path.relative_to(site_dir).as_posix(),
                "sources": sources_path.relative_to(site_dir).as_posix(),
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
