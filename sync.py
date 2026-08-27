#!/usr/bin/env python3
"""Push docs from a folder to a Datalumo API source."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

EXTENSIONS = {
    ".md": "text/markdown",
    ".mdx": "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
}
SKIP_DIRS = {".git", "node_modules", "vendor", ".github"}
BATCH = 50


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        if default is not None:
            return default
        raise SystemExit(f"Missing required input: {name}")
    return value


def title_from(path: Path, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def collect(root: Path) -> list[dict]:
    pages: list[dict] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            path = Path(dirpath) / name
            mime = EXTENSIONS.get(path.suffix.lower())
            if mime is None:
                continue
            rel = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            page = {
                "external_id": rel,
                "name": title_from(path, text),
                "content": text,
                "content_mime": mime,
            }
            pages.append(page)
    pages.sort(key=lambda item: item["external_id"])
    return pages


def add_urls(pages: list[dict], base_url: str) -> None:
    if not base_url:
        return
    prefix = base_url.rstrip("/")
    for page in pages:
        page["source_url"] = f"{prefix}/{page['external_id']}"


def post_batch(api_url: str, org: str, source: str, token: str, batch: list[dict]) -> int:
    url = f"{api_url.rstrip('/')}/api/v1/{org}/sources/{source}/pages/batch"
    body = json.dumps({"pages": batch}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "datalumo-github-action",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            status = response.status
            response.read()
            return status
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Datalumo API {error.code} on batch of {len(batch)}: {detail[:800]}") from error


def main() -> None:
    token = env("DATALUMO_TOKEN")
    org = env("DATALUMO_ORG")
    source = env("DATALUMO_SOURCE")
    relative = env("DATALUMO_PATH", "docs")
    base_url = env("DATALUMO_BASE_URL", "")
    api_url = env("DATALUMO_API_URL", "https://datalumo.app")
    workspace = Path(env("DATALUMO_WORKSPACE", os.getcwd()))

    root = (workspace / relative).resolve()
    if not root.is_dir():
        raise SystemExit(f"Docs path does not exist: {root}")

    pages = collect(root)
    add_urls(pages, base_url)
    if not pages:
        print(f"No Markdown, HTML, or text files under {root}")
        return

    print(f"Syncing {len(pages)} page(s) from {root} to source {source}")
    sent = 0
    for start in range(0, len(pages), BATCH):
        batch = pages[start : start + BATCH]
        status = post_batch(api_url, org, source, token, batch)
        sent += len(batch)
        print(f"Pushed {sent}/{len(pages)} (HTTP {status})")
    print("Done. Indexing continues in Datalumo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
