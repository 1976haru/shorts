"""Baseline guards for the engine/UI split (see CLAUDE.md / AGENTS.md).

These tests never import app.py, so no Tk window is created.
"""

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI_MODULES = ("tkinter", "tkinterdnd2", "pygame")
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache"}


def _repo_files():
    """Files tracked by git (falls back to a filtered walk without git)."""
    try:
        out = subprocess.run(
            ["git", "-c", "core.quotepath=off", "ls-files", "-z"],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        names = [n for n in out.decode("utf-8").split("\0") if n]
        return [ROOT / n for n in names if (ROOT / n).is_file()]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            files.extend(Path(dirpath) / f for f in filenames)
        return files


def _version_from_file():
    first = (ROOT / "VERSION.txt").read_text(encoding="utf-8-sig").splitlines()[0]
    match = re.fullmatch(r"ShortsMaker Studio v(\d+\.\d+\.\d+)", first.strip())
    if not match:
        raise AssertionError(f"Unexpected VERSION.txt first line: {first!r}")
    return match.group(1)


def _app_version():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.M)
    if not match:
        raise AssertionError("APP_VERSION not found in app.py")
    return match.group(1)


class VersionTests(unittest.TestCase):
    def test_version_txt_matches_app_version(self):
        self.assertEqual(_version_from_file(), _app_version())


class BatchFileTests(unittest.TestCase):
    def test_bat_files_are_ascii_only(self):
        bats = {p for p in _repo_files() if p.suffix.lower() == ".bat"}
        bats.update(ROOT.glob("*.bat"))
        self.assertTrue(bats, "no .bat files found")
        for path in sorted(bats):
            with self.subTest(bat=path.name):
                self.assertTrue(path.name.isascii(), f"non-ASCII file name: {path.name!r}")
                data = path.read_bytes()
                self.assertTrue(data.isascii(), f"non-ASCII content in {path.name}")


ENGINE_FILES = ("shorts_core.py", "shorts_cli.py")
ENGINE_FORBIDDEN = GUI_MODULES + ("app",)


class EngineIsolationTests(unittest.TestCase):
    def test_engine_files_have_no_gui_imports(self):
        for filename in ENGINE_FILES:
            with self.subTest(file=filename):
                tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
                found = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        names = [node.module or ""]
                    else:
                        continue
                    for name in names:
                        if name.split(".")[0] in ENGINE_FORBIDDEN:
                            found.append(name)
                self.assertEqual(found, [])

    def test_import_engine_does_not_load_gui_modules(self):
        # shorts_cli reroutes sys.stdout to stderr on import, so keep a handle.
        code = (
            "import sys\n"
            "out = sys.stdout\n"
            "import shorts_core, shorts_cli\n"
            f"loaded = [m for m in {ENGINE_FORBIDDEN!r} if m in sys.modules]\n"
            "out.write(','.join(loaded) + '\\n')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "", f"GUI modules loaded: {result.stdout.strip()}")


class LegacyVersionStringTests(unittest.TestCase):
    def test_no_legacy_version_strings(self):
        # Built dynamically so this file does not match itself.
        legacy = ["0.5." + "1", "0.5." + "2"]
        hits = []
        for path in _repo_files():
            rel = path.relative_to(ROOT).as_posix()
            if rel == "requirements.txt" or rel.startswith("docs/"):
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue  # binary
            text = data.decode("utf-8", errors="ignore")
            for needle in legacy:
                if needle in text or needle in rel:
                    hits.append(f"{rel}: {needle}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
