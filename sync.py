#!/usr/bin/env python3
"""Push docs from a folder to a Datalumo API source."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
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
USER_AGENT = "datalumo-github-action"


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


def external_id_for(rel: str) -> str:
    return str(Path(rel).with_suffix("")).replace("\\", "/")


def collect(root: Path) -> list[dict]:
    pages: list[dict] = []
    seen: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            path = Path(dirpath) / name
            mime = EXTENSIONS.get(path.suffix.lower())
            if mime is None:
                continue
            rel = path.relative_to(root).as_posix()
            external_id = external_id_for(rel)
            if external_id in seen:
                raise SystemExit(
                    f"Two files map to external_id {external_id!r}: {seen[external_id]} and {rel}"
                )
            seen[external_id] = rel
            text = path.read_text(encoding="utf-8")
            pages.append(
                {
                    "external_id": external_id,
                    "name": title_from(path, text),
                    "content": text,
                    "content_mime": mime,
                }
            )

    pages.sort(key=lambda item: item["external_id"])
    return pages


def add_urls(pages: list[dict], base_url: str) -> None:
    if not base_url:
        return
    prefix = base_url.rstrip("/")
    for page in pages:
        page["source_url"] = f"{prefix}/{page['external_id']}"


def api_request(
    api_url: str,
    org: str,
    source: str,
    token: str,
    method: str,
    path: str,
    body: dict | None = None,
) -> tuple[int, dict | None]:
    url = f"{api_url.rstrip('/')}/api/v1/{org}/sources/{source}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8")) if raw else None
            return response.status, payload
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Datalumo API {error.code} on {method} {path}: {detail[:800]}") from error


def post_batch(api_url: str, org: str, source: str, token: str, batch: list[dict]) -> int:
    status, _ = api_request(api_url, org, source, token, "POST", "/pages/batch", {"pages": batch})
    return status


def list_external_ids(api_url: str, org: str, source: str, token: str) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None

    while True:
        query = urllib.parse.urlencode(
            {"per_page": "100", **({"cursor": cursor} if cursor else {})}
        )
        _, payload = api_request(api_url, org, source, token, "GET", f"/pages?{query}")
        if not payload:
            break
        for page in payload.get("data") or []:
            external_id = page.get("external_id")
            if external_id:
                ids.append(external_id)
        cursor = (payload.get("meta") or {}).get("next_cursor")
        if not cursor:
            break

    return ids


def delete_page(api_url: str, org: str, source: str, token: str, external_id: str) -> None:
    encoded = urllib.parse.quote(external_id, safe="")
    api_request(api_url, org, source, token, "DELETE", f"/pages/{encoded}")


def kick_index(api_url: str, org: str, source: str, token: str) -> None:
    api_request(api_url, org, source, token, "POST", "/index")


def prune(
    api_url: str,
    org: str,
    source: str,
    token: str,
    keep: set[str],
    log=print,
) -> int:
    stale = [external_id for external_id in list_external_ids(api_url, org, source, token) if external_id not in keep]
    for external_id in stale:
        delete_page(api_url, org, source, token, external_id)
        log(f"Deleted {external_id}.")
    return len(stale)


def sync(
    api_url: str,
    org: str,
    source: str,
    token: str,
    pages: list[dict],
    log=print,
) -> dict[str, int]:
    if not pages:
        raise SystemExit("No markdown files found. Refusing to sync an empty docs set.")

    log(f"Syncing {len(pages)} page(s) to source {source}")
    sent = 0
    for start in range(0, len(pages), BATCH):
        batch = pages[start : start + BATCH]
        status = post_batch(api_url, org, source, token, batch)
        sent += len(batch)
        log(f"Pushed {sent}/{len(pages)} (HTTP {status})")

    deleted = prune(api_url, org, source, token, {page["external_id"] for page in pages}, log=log)
    kick_index(api_url, org, source, token)
    log("Indexing kicked.")
    return {"pushed": sent, "deleted": deleted}


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
    sync(api_url, org, source, token, pages)
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
