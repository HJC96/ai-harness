"""Exercise installation in disposable checkouts; never touch user configuration."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-harness-install-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for directory in ("codex/agents", "shared/skills/book-plan", "shared/skills/book-write", "scripts"):
            (self.root / directory).mkdir(parents=True)
        (self.root / "codex/skills.list").write_text("book-plan\nbook-write\n", encoding="utf-8")
        shutil.copy2(REPO / "scripts/install-codex.sh", self.root / "scripts/install-codex.sh")

    def run_install(self):
        return subprocess.run(
            ["bash", str(self.root / "scripts/install-codex.sh")],
            cwd=self.root.parent,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_install_from_elsewhere_is_relative_and_repeatable(self):
        for _ in range(2):
            result = self.run_install()
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / ".codex/agents").resolve(), self.root / "codex/agents")
        self.assertEqual((self.root / ".agents/skills/book-plan").resolve(), self.root / "shared/skills/book-plan")
        self.assertFalse((self.root / ".codex/agents").readlink().is_absolute())

    def test_conflict_is_detected_before_any_connection_is_created(self):
        existing = self.root / ".agents/skills/book-write"
        existing.mkdir(parents=True)
        user_file = existing / "keep.txt"
        user_file.write_text("user content", encoding="utf-8")
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(user_file.read_text(encoding="utf-8"), "user content")
        self.assertFalse((self.root / ".codex").exists())

    def test_wrong_or_dangling_connection_is_preserved(self):
        (self.root / ".codex").mkdir()
        connection = self.root / ".codex/agents"
        connection.symlink_to("../user-agents")
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(str(connection.readlink()), "../user-agents")
        self.assertFalse((self.root / ".agents").exists())

    def test_symlinked_parent_is_not_followed(self):
        outside = self.root / "outside"
        outside.mkdir()
        (self.root / ".codex").symlink_to(outside, target_is_directory=True)
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(outside.iterdir()), [])

    def test_broad_link_migration_preserves_unselected_sources(self):
        unrelated = self.root / "shared/skills/another-workflow"
        unrelated.mkdir()
        (unrelated / "SKILL.md").write_text("user content", encoding="utf-8")
        (self.root / ".agents").mkdir()
        (self.root / ".agents/skills").symlink_to("../shared/skills")
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / ".agents/skills").is_symlink())
        self.assertEqual((unrelated / "SKILL.md").read_text(encoding="utf-8"), "user content")
        self.assertFalse((self.root / ".agents/skills/another-workflow").exists())
        self.assertEqual((self.root / ".agents/skills/book-write").resolve(), self.root / "shared/skills/book-write")


if __name__ == "__main__":
    unittest.main()
