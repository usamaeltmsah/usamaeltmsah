"""Rewrite the README activity section from the GitHub public events API.

Unlike jamesgeorge007/github-activity-readme, this includes push and
repository-creation events, so the list stays current for accounts whose
public activity is mostly commits.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

START = "<!--START_SECTION:activity-->"
END = "<!--END_SECTION:activity-->"
MAX_LINES = 5


def repo_link(name: str) -> str:
    return f"[{name}](https://github.com/{name})"


def describe(event: dict) -> str | None:
    kind = event["type"]
    repo = event["repo"]["name"]
    payload = event.get("payload", {})
    action = payload.get("action")

    if kind == "PushEvent":
        branch = payload.get("ref", "").removeprefix("refs/heads/")
        return f"⬆️ Pushed to `{branch}` in {repo_link(repo)}"
    if kind == "CreateEvent" and payload.get("ref_type") == "repository":
        return f"🎉 Created repository {repo_link(repo)}"
    if kind == "PullRequestEvent" and action in ("opened", "closed"):
        pr = payload["pull_request"]
        url = f"https://github.com/{repo}/pull/{pr['number']}"
        verb = "🔀 Merged" if pr.get("merged") else ("💪 Opened" if action == "opened" else "❌ Closed")
        return f"{verb} PR [#{pr['number']}]({url}) in {repo_link(repo)}"
    if kind == "IssuesEvent" and action in ("opened", "closed"):
        issue = payload["issue"]
        verb = "❗ Opened" if action == "opened" else "✔️ Closed"
        return f"{verb} issue [#{issue['number']}]({issue['html_url']}) in {repo_link(repo)}"
    if kind == "ReleaseEvent" and action == "published":
        release = payload["release"]
        return f"🚀 Released [{release['tag_name']}]({release['html_url']}) in {repo_link(repo)}"
    if kind == "WatchEvent":
        return f"⭐ Starred {repo_link(repo)}"
    return None


def build_lines(events: list[dict], limit: int = MAX_LINES) -> list[str]:
    """Describe events newest first, collapsing consecutive pushes to one repo/branch."""
    ordered = sorted(events, key=lambda e: e["created_at"], reverse=True)
    lines: list[str] = []
    counts: list[int] = []
    for event in ordered:
        text = describe(event)
        if text is None:
            continue
        if lines and text == lines[-1] and event["type"] == "PushEvent":
            counts[-1] += 1
            continue
        if len(lines) == limit:
            break
        lines.append(text)
        counts.append(1)
    return [
        text.replace("⬆️ Pushed to", f"⬆️ Pushed {count} times to", 1) if count > 1 else text
        for text, count in zip(lines, counts)
    ]


def replace_section(readme: str, lines: list[str]) -> str:
    pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(readme):
        raise ValueError(f"README is missing the {START} ... {END} markers")
    body = "\n".join(f"{i}. {line}" for i, line in enumerate(lines, start=1))
    return pattern.sub(lambda _: f"{START}\n{body}\n{END}", readme, count=1)


def fetch_events(username: str, token: str | None) -> list[dict]:
    request = urllib.request.Request(
        f"https://api.github.com/users/{username}/events/public?per_page=100",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "profile-activity"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    username = os.environ.get("GITHUB_USERNAME") or os.environ["GITHUB_REPOSITORY_OWNER"]
    readme_path = Path(os.environ.get("README_PATH", "README.md"))
    lines = build_lines(fetch_events(username, os.environ.get("GITHUB_TOKEN")))
    if not lines:
        print("No public activity found; leaving README unchanged.")
        return 0
    readme = readme_path.read_text(encoding="utf-8")
    updated = replace_section(readme, lines)
    if updated != readme:
        readme_path.write_text(updated, encoding="utf-8")
        print("README activity updated.")
    else:
        print("README activity already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
