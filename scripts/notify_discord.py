#!/usr/bin/env python3
"""Send a Discord notification for the generated daily paper digest."""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL is not set; skipping Discord notification.")
        return 0

    report_date = os.getenv("REPORT_DATE") or dt.datetime.now(dt.timezone.utc).date().isoformat()
    repository = os.getenv("GITHUB_REPOSITORY", "")
    branch = os.getenv("GITHUB_REF_NAME", "main")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    run_url = f"{server_url}/{repository}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}" if repository else ""

    report_path = Path("reports") / f"{report_date}.md"
    sources_path = Path("sources") / f"{report_date}.md"
    report_url = github_blob_url(server_url, repository, branch, report_path)
    sources_url = github_blob_url(server_url, repository, branch, sources_path)

    focus_titles = extract_focus_titles(report_path)
    description_lines = [
        f"日期：{report_date}",
        "",
        "重點關注：",
        *(f"{index}. {title}" for index, title in enumerate(focus_titles[:5], start=1)),
        "",
        f"[查看正式簡報]({report_url})",
        f"[查看來源與評分]({sources_url})",
    ]
    if run_url:
        description_lines.append(f"[查看 Action 執行紀錄]({run_url})")

    payload = {
        "embeds": [
            {
                "title": "每日 AI 論文簡報已產生",
                "description": "\n".join(description_lines)[:3900],
                "color": 5793266,
            }
        ]
    }
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()
    except urllib.error.URLError as exc:
        print(f"Discord notification failed: {exc}", file=sys.stderr)
        return 1

    print("Discord notification sent.")
    return 0


def github_blob_url(server_url: str, repository: str, branch: str, path: Path) -> str:
    if not repository:
        return str(path).replace("\\", "/")
    return f"{server_url}/{repository}/blob/{branch}/{str(path).replace('\\', '/')}"


def extract_focus_titles(report_path: Path) -> list[str]:
    if not report_path.exists():
        return ["簡報檔案尚未找到"]
    titles: list[str] = []
    in_focus = False
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## 重點關注"):
            in_focus = True
            continue
        if in_focus and line.startswith("## "):
            break
        if in_focus and line.startswith("### "):
            title = line[4:].strip()
            if ". " in title:
                title = title.split(". ", 1)[1]
            titles.append(title)
    return titles or ["本期沒有解析到重點關注標題"]


if __name__ == "__main__":
    raise SystemExit(main())
