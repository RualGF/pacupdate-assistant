import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import main
from config import load_packages_sources
from flatpak import fetch_release_notes, get_flatpak_updates, parse_release_tables
from models import PackageUpdate
from updater import resolve_one_changelog


ARTICLE = """
<h2>Upcoming release</h2>
<table><tr><th>Linux</th></tr><tr><td>8.1.0 (300)</td></tr></table>
<h2>Released</h2>
<h3 id="release-8-1">Release day</h3>
<table>
  <tr><th>Windows</th><th>Linux</th></tr>
  <tr><td>8.1.0 (210)</td><td>8.1.0 (200)</td></tr>
</table>
<table>
  <tr><th>Description</th><th>Platforms</th></tr>
  <tr><td>Wayland video fix</td><td>Windows<br />Linux</td></tr>
  <tr><td>Windows-only fix</td><td>Windows</td></tr>
</table>
<table>
  <tr><th>Windows</th><th>Linux</th></tr>
  <tr><td>8.1.0 (220)</td><td>8.1.0 (201)</td></tr>
</table>
<table>
  <tr><th>Description</th><th>Platforms</th></tr>
  <tr><td>Fix in a different build on the same day</td><td>Linux</td></tr>
</table>
"""
PAGE = f'<script type="application/ld+json">{json.dumps({"articleBody": ARTICLE})}</script>'
INSTALLED = [["us.zoom.Zoom", "8.0.0.100", "x86_64", "stable", "flathub", "system"]]
NOTES_URL = "https://example.org/releases"


class FlatpakUpdatesTest(unittest.TestCase):
    def test_uses_exact_linux_build_and_keeps_editions_separate(self):
        result = parse_release_tables(PAGE, "8.1.0.200", NOTES_URL, "Linux")
        self.assertEqual(result["body"], "- Wayland video fix")
        self.assertEqual(result["url"], f"{NOTES_URL}#release-8-1")
        for version in ("8.1.0.20", "8.1.0.210", "8.1.0.300", "8.1.0"):
            with self.subTest(version=version):
                self.assertIsNone(parse_release_tables(PAGE, version, NOTES_URL, "Linux"))
        windows = parse_release_tables(PAGE, "8.1.0.210", NOTES_URL, "Windows")
        self.assertIn("Windows-only fix", windows["body"])

    def test_remote_lookup_matches_the_installed_branch(self):
        remote = [["us.zoom.Zoom", "8.1.0.200", "x86_64", "beta"]]
        with patch("flatpak._list_rows", side_effect=[INSTALLED, remote]) as lookup:
            self.assertEqual(get_flatpak_updates(load_packages_sources()), ([], False))
        self.assertIn("--system", lookup.call_args.args[0])
        self.assertEqual(lookup.call_args.args[0][-1], "flathub")

    def test_detects_configured_and_unconfigured_apps_in_one_remote_query(self):
        installed = [*INSTALLED, ["org.example.Editor", "1.0", "x86_64", "stable", "flathub", "system"]]
        remote = [["us.zoom.Zoom", "8.1.0.200", "x86_64", "stable"],
                  ["org.example.Editor", "1.1", "x86_64", "stable"]]
        sources = {"zoom": "flatpak:us.zoom.Zoom"}
        with patch("flatpak._list_rows", side_effect=[installed, remote]) as lookup:
            updates, failed = get_flatpak_updates(sources)
        self.assertFalse(failed)
        self.assertEqual([(u.name, u.new_pkgver) for u in updates],
                         [("zoom", "8.1.0.200"), ("org.example.Editor", "1.1")])
        self.assertEqual(lookup.call_count, 2)

    def test_uses_exact_appstream_release_and_branch_without_web_configuration(self):
        catalog = """<components>
          <component><id>org.example.Editor</id>
            <bundle type="flatpak">app/org.example.Editor/x86_64/beta</bundle>
            <releases><release version="1.2"><description><p>Beta notes</p></description></release></releases>
          </component>
          <component><id>org.example.Editor</id>
            <bundle type="flatpak">app/org.example.Editor/x86_64/stable</bundle>
            <releases>
              <release version="1.20"><description><p>Future notes</p></description></release>
              <release version="1.2"><description><p>Stable notes</p></description></release>
            </releases>
          </component>
        </components>"""
        update = PackageUpdate("editor", "1.1", "", "1.2", "", flatpak_ref="org.example.Editor/x86_64/stable")
        with TemporaryDirectory() as temp, patch("flatpak._appstream_directory", return_value=Path(temp)):
            (Path(temp) / "appstream.xml").write_text(catalog)
            self.assertEqual(resolve_one_changelog(update, {}, {}, None),
                             {"type": "text", "body": "Stable notes", "url": ""})
            update.new_pkgver = "1.21"
            self.assertIsNone(fetch_release_notes(update, {}))

    def test_main_shows_notes_and_handles_unconfirmed_and_same_version(self):
        for version, expected, fetch_notes in (
            ("8.1.0.200", "Wayland video fix", True),
            ("8.1.0.999", "Notas oficiales sin confirmar", True),
            ("8.0.0.100", "actualización del paquete", False),
        ):
            with self.subTest(version=version):
                self.check_summary(version, expected, fetch_notes)

    def check_summary(self, version, expected, fetch_notes):
        remote = [["us.zoom.Zoom", version, "x86_64", "stable"]]
        output = io.StringIO()
        with (
            patch("flatpak._list_rows", side_effect=[INSTALLED, remote]),
            patch("flatpak._appstream_directory", return_value=None),
            patch("flatpak.requests.get", return_value=Mock(text=PAGE)) as request,
            patch("main.get_updates", return_value=[]),
            patch("main.get_aur_updates", return_value=[]),
            patch("main.load_seen_packages", return_value=set()),
            patch("main.save_seen_packages"),
            patch("main.get_package_info", return_value={}),
            patch("main.get_package_groups", return_value={}),
            patch("ui.get_package_info", return_value={}),
            patch("ui.load_github_repo_cache", return_value={}),
            redirect_stdout(output),
        ):
            main.main()
        self.assertIn("Flatpak", output.getvalue())
        self.assertIn(expected, output.getvalue())
        self.assertEqual(request.called, fetch_notes)
