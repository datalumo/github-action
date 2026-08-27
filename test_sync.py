import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import sync


class CollectTests(unittest.TestCase):
    def test_external_id_drops_the_extension(self):
        self.assertEqual(sync.external_id_for("introduction.md"), "introduction")
        self.assertEqual(sync.external_id_for("guides/install.mdx"), "guides/install")

    def test_collect_uses_the_first_heading_and_slug(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "introduction.md").write_text("# Welcome to Datalumo\n\nBody.\n")
            (root / "nested").mkdir()
            (root / "nested" / "install.md").write_text("No heading here.\n")

            pages = sync.collect(root)

            self.assertEqual(
                [page["external_id"] for page in pages],
                ["introduction", "nested/install"],
            )
            self.assertEqual(pages[0]["name"], "Welcome to Datalumo")
            self.assertEqual(pages[1]["name"], "Install")
            self.assertEqual(pages[0]["content_mime"], "text/markdown")

    def test_collect_rejects_two_files_with_the_same_slug(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "intro.md").write_text("# Intro\n")
            (root / "intro.html").write_text("<h1>Intro</h1>")

            with self.assertRaises(SystemExit) as raised:
                sync.collect(root)

            self.assertIn("intro", str(raised.exception))

    def test_citation_urls_do_not_include_the_file_extension(self):
        pages = [{"external_id": "introduction"}]
        sync.add_urls(pages, "https://datalumo.app/docs/")
        self.assertEqual(pages[0]["source_url"], "https://datalumo.app/docs/introduction")


class SyncTests(unittest.TestCase):
    def test_sync_pushes_prunes_and_indexes(self):
        pages = [{"external_id": "introduction", "name": "Introduction", "content": "# Introduction"}]
        calls: list[tuple[str, str]] = []

        def fake_request(api_url, org, source, token, method, path, body=None):
            calls.append((method, path))
            if method == "GET" and path.startswith("/pages?"):
                return 200, {
                    "data": [
                        {"external_id": "introduction"},
                        {"external_id": "removed-page"},
                    ],
                    "meta": {"next_cursor": None},
                }
            return 202, {}

        with patch.object(sync, "api_request", side_effect=fake_request):
            result = sync.sync("https://datalumo.app", "org", "docs", "token", pages, log=lambda *_: None)

        self.assertEqual(result, {"pushed": 1, "deleted": 1})
        self.assertIn(("POST", "/pages/batch"), calls)
        self.assertTrue(any(method == "DELETE" and path.endswith("/removed-page") for method, path in calls))
        self.assertNotIn(("DELETE", "/pages/introduction"), calls)
        self.assertIn(("POST", "/index"), calls)

    def test_sync_follows_the_list_cursor(self):
        pages = [{"external_id": "keep"}]
        calls: list[str] = []

        def fake_request(api_url, org, source, token, method, path, body=None):
            calls.append(path)
            if method == "GET" and "cursor=" not in path:
                return 200, {
                    "data": [{"external_id": "keep"}],
                    "meta": {"next_cursor": "next"},
                }
            if method == "GET":
                return 200, {
                    "data": [{"external_id": "gone"}],
                    "meta": {"next_cursor": None},
                }
            return 202, {}

        with patch.object(sync, "api_request", side_effect=fake_request):
            result = sync.sync("https://datalumo.app", "org", "docs", "token", pages, log=lambda *_: None)

        self.assertEqual(result["deleted"], 1)
        self.assertTrue(any("cursor=next" in path for path in calls))

    def test_sync_refuses_an_empty_set(self):
        with self.assertRaises(SystemExit) as raised:
            sync.sync("https://datalumo.app", "org", "docs", "token", [], log=lambda *_: None)

        self.assertIn("empty", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
