# Datalumo Sync

GitHub Action that pushes Markdown and docs from a repository into a [Datalumo](https://datalumo.app) knowledge source.

Use it when your docs live in git. On push, the files are synced. Visitors get search and chat that stay on your content.

## Use it

1. In Datalumo, create a source of type **API**.
2. Create an API key with `pages.write`. Limit it to that source if you can.
3. Copy your **organisation public id** (the UUID, not the slug).
4. In the docs repo, add the secrets and this workflow.

```yaml
name: Sync docs to Datalumo

on:
  push:
    branches: [main]
    paths:
      - "docs/**"
      - ".github/workflows/datalumo.yml"

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: datalumo/github-action@v1
        with:
          api_key: ${{ secrets.DATALUMO_TOKEN }}
          organisation: ${{ secrets.DATALUMO_ORG }}
          source: docs
          path: docs
          base_url: https://example.com/docs
```

`external_id` is the file path, so a later run updates the same pages instead of duplicating them.

## Inputs

| Input | Required | Default | What it is |
|---|---|---|---|
| `api_key` | yes | | Organisation API key with `pages.write` |
| `organisation` | yes | | Organisation public id (UUID) |
| `source` | yes | | API source slug or public id |
| `path` | no | `docs` | Folder to sync, relative to the repo |
| `base_url` | no | | Public docs URL prefix for citations |
| `api_url` | no | `https://datalumo.app` | Change only for a self-hosted install |

## What it uploads

`.md`, `.mdx`, `.markdown`, `.html`, `.htm`, and `.txt`. It skips `.git`, `node_modules`, `vendor`, and `.github`.

Title comes from the first `# heading`, or the file name. After a push, Datalumo indexes in the background. Watch the source page in the dashboard until it says Ready.

## Marketplace

This repository is the listed Action. Publish a release from `action.yml` and tick **Publish this Action to the GitHub Marketplace**. See [GitHub's listing steps](https://docs.github.com/en/actions/how-tos/create-and-publish-actions/publish-in-github-marketplace).
