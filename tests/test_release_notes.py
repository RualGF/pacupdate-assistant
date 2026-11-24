import json
import unittest
from unittest.mock import patch

import github
import gitlab
from models import PackageUpdate
from updater import resolve_one_changelog


METAINFO = """<component><releases>
  <release version="2.0.10"><description><p>Another version</p></description></release>
  <release version="2.0.1"><description><ul><li>Fix window controls</li></ul></description></release>
</releases></component>"""


class ReleaseNotesTest(unittest.TestCase):
    def test_github_replaces_placeholder_with_exact_appstream_release(self):
        releases = [
            {"tag_name": "v2.0.10", "body": "Another release"},
            {"tag_name": "v2.0.1", "body": "New version bump"},
        ]
        tree = {"tree": [{"path": "org.example.App.metainfo.xml", "type": "blob"}]}
        with patch("github._fetch", side_effect=[json.dumps(releases), json.dumps(tree), METAINFO]) as fetch:
            result = github.fetch_release_notes("example/app", "1:2.0.1", None)
        self.assertEqual(result["body"], "- Fix window controls")
        self.assertIn("/blob/v2.0.1/", result["url"])
        self.assertIn("ref=v2.0.1", fetch.call_args.args[0])

    def test_github_published_notes_avoid_file_lookup(self):
        releases = [{"tag_name": "v2.0.1", "body": "New window controls", "html_url": "https://example.org/2.0.1"}]
        with patch("github._fetch", return_value=json.dumps(releases)) as fetch:
            result = github.fetch_release_notes("example/app", "2.0.1", None)
        self.assertEqual(result["body"], "New window controls")
        self.assertEqual(fetch.call_count, 1)

    def test_tag_only_returns_reference_when_exact_notes_are_missing(self):
        tags = [{"name": "v2.0.1"}]
        responses = ["[]", json.dumps(tags), None, '{"tree":[]}']
        with patch("github._fetch", side_effect=responses):
            result = github.fetch_release_notes("example/app", "2.0.1", None)
        self.assertEqual(result, {"type": "reference", "url": "https://github.com/example/app/tree/v2.0.1"})

    def test_gitlab_extracts_only_the_matching_section_from_configured_file(self):
        releases = [{"tag_name": "release-2.0.1", "description": "**Full Changelog**: https://example.org/compare"}]
        news = """# Changelog
## [2.0.10] - 2026-12-01
Another release.
## [2.0.1] - 2026-11-24
### Fixed
- Fix window controls.
## [2.0.0] - 2026-11-01
Previous release.
"""
        with patch("gitlab._fetch", side_effect=[releases, news]) as fetch:
            result = gitlab.fetch_release_notes("example/app", "2.0.1", notes_file="docs/CHANGELOG.md")
        self.assertEqual(result["body"], "### Fixed\n- Fix window controls.")
        self.assertIn("docs%2FCHANGELOG.md/raw?ref=release-2.0.1", fetch.call_args.args[0])

    def test_unclassified_package_can_use_a_trusted_discovered_repository(self):
        update = PackageUpdate("app", "2.0.0", "1", "2.0.1", "1")
        cache = {"app": {"repo": "example/app", "confidence": "high"}}
        with patch("updater.fetch_release_notes") as fetch:
            resolve_one_changelog(update, {}, cache, None)
        fetch.assert_called_once_with("example/app", "2.0.1", None, None)
