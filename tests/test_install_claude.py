"""일회용 체크아웃과 임시 CLAUDE_HOME에서만 설치를 검증한다. 사용자 설정은 건드리지 않는다."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = ["교재", "교재-설계", "챕터-집필", "챕터-검수", "교재-엮기"]
AGENTS = ["curriculum-architect", "chapter-writer", "technical-reviewer",
          "learner-advocate", "learning-editor"]
ORCH = ["교재-파이프라인.md", "산출물-계약.md", "book.py"]


class InstallClaudeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-harness-claude-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root, self.home = base / "repo", base / "home"
        self.home.mkdir()

        (self.root / "scripts").mkdir(parents=True)
        (self.root / "claude/agents").mkdir(parents=True)
        (self.root / "shared/orchestration").mkdir(parents=True)
        (self.root / "shared/instructions").mkdir(parents=True)
        (self.root / "README.md").write_text("fake\n", encoding="utf-8")
        for name in SKILLS:
            d = self.root / "shared/skills" / name
            d.mkdir(parents=True)
            shutil.copy2(REPO / "shared/skills" / name / "SKILL.md", d / "SKILL.md")
        for name in AGENTS:
            shutil.copy2(REPO / "claude/agents" / f"{name}.md", self.root / "claude/agents" / f"{name}.md")
        for name in ORCH:
            shutil.copy2(REPO / "shared/orchestration" / name, self.root / "shared/orchestration" / name)
        shutil.copy2(REPO / "shared/instructions/교재-공통규약.md", self.root / "shared/instructions/교재-공통규약.md")
        shutil.copy2(REPO / "scripts/install-claude.sh", self.root / "scripts/install-claude.sh")
        shutil.copy2(REPO / "claude/CLAUDE.md", self.root / "claude/CLAUDE.md")

    def run_script(self, *args, config_dir=None):
        return subprocess.run(
            ["bash", str(self.root / "scripts/install-claude.sh"), *args],
            env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(self.home),
                 "CLAUDE_HOME": str(self.home / ".claude"),
                 **({"CLAUDE_CONFIG_DIR": str(config_dir)} if config_dir else {})},
            text=True, capture_output=True, check=False)

    def expected(self):
        c = self.home / ".claude"
        return ([(c / "skills" / n, self.root / "shared/skills" / n) for n in SKILLS]
                + [(c / "agents" / f"{n}.md", self.root / "claude/agents" / f"{n}.md") for n in AGENTS]
                + [(c / "orchestration" / n, self.root / "shared/orchestration" / n) for n in ORCH]
                + [(c / "instructions/교재-공통규약.md", self.root / "shared/instructions/교재-공통규약.md")])

    def test_links_every_managed_file(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for dest, src in self.expected():
            self.assertTrue(dest.is_symlink(), f"{dest} 링크 없음")
            self.assertEqual(Path(dest.readlink()), src)

    def test_leaves_unmanaged_skills_alone(self):
        """저장소의 다른 계열 스킬(book-*)은 연결하지 않는다."""
        (self.root / "shared/skills/book-plan").mkdir(parents=True)
        self.run_script()
        self.assertFalse((self.home / ".claude/skills/book-plan").exists())

    def test_never_overwrites_a_real_file(self):
        victim = self.home / ".claude/skills/교재"
        victim.mkdir(parents=True)
        (victim / "SKILL.md").write_text("사용자의 것\n", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(victim.is_symlink())
        self.assertEqual((victim / "SKILL.md").read_text(encoding="utf-8"), "사용자의 것\n")

    def test_install_is_idempotent(self):
        self.assertEqual(self.run_script().returncode, 0)
        again = self.run_script()
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.run_script("--check").returncode, 0)

    def test_uninstall_removes_only_our_links(self):
        self.run_script()
        foreign = self.home / ".claude/skills/형광펜"
        foreign.mkdir(parents=True)
        (foreign / "SKILL.md").write_text("남의 것\n", encoding="utf-8")
        self.assertEqual(self.run_script("--uninstall").returncode, 0)
        for dest, _ in self.expected():
            self.assertFalse(dest.exists(), f"{dest} 가 남아 있다")
        self.assertTrue((foreign / "SKILL.md").is_file())

    def test_migrates_directory_link_to_files(self):
        """예전 방식(디렉터리 통째 링크)은 파일별 링크로 교체된다."""
        c = self.home / ".claude"
        c.mkdir()
        (c / "orchestration").symlink_to(self.root / "shared/orchestration")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertFalse((c / "orchestration").is_symlink())
        for name in ORCH:
            self.assertTrue((c / "orchestration" / name).is_symlink())

    def test_doctor_passes_after_install(self):
        self.run_script()
        result = self.run_script("--doctor")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_late_conflict_leaves_everything_uninstalled(self):
        victim = self.home / ".claude/instructions/교재-공통규약.md"
        victim.parent.mkdir(parents=True)
        victim.write_text("개인 규약", encoding="utf-8")
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.home / ".claude/skills").exists())
        self.assertEqual(victim.read_text(encoding="utf-8"), "개인 규약")

    def test_migration_is_not_started_when_another_path_conflicts(self):
        c = self.home / ".claude"
        (c / "agents").mkdir(parents=True)
        (c / "orchestration").symlink_to(self.root / "shared/orchestration")
        (c / "agents/learning-editor.md").write_text("개인 역할", encoding="utf-8")
        self.assertEqual(self.run_script().returncode, 1)
        self.assertTrue((c / "orchestration").is_symlink())

    def test_symlink_parent_is_never_followed(self):
        c, foreign = self.home / ".claude", self.home / "foreign"
        c.mkdir()
        foreign.mkdir()
        (c / "skills").symlink_to(foreign)
        self.assertEqual(self.run_script().returncode, 1)
        self.assertEqual(list(foreign.iterdir()), [])

    def test_uninstall_preserves_foreign_orchestration_file_and_finishes(self):
        self.assertEqual(self.run_script().returncode, 0)
        foreign = self.home / ".claude/orchestration/personal.md"
        foreign.write_text("내 파일", encoding="utf-8")
        self.assertEqual(self.run_script("--uninstall").returncode, 0)
        self.assertTrue(foreign.exists())
        for dest, _ in self.expected():
            self.assertFalse(dest.is_symlink(), str(dest))

    def test_dry_run_and_doctor_need_no_installation(self):
        for flag in ("--dry-run", "--doctor"):
            result = self.run_script(flag)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.home / ".claude").exists())

    def test_missing_skill_fails_before_any_mutation(self):
        (self.root / "shared/skills/교재-엮기/SKILL.md").unlink()
        self.assertEqual(self.run_script().returncode, 1)
        self.assertFalse((self.home / ".claude").exists())

    def test_doctor_reports_malformed_metadata(self):
        (self.root / "claude/agents/learning-editor.md").write_text("no metadata", encoding="utf-8")
        result = self.run_script("--doctor")
        self.assertEqual(result.returncode, 1)
        self.assertIn("frontmatter", result.stdout)

    def test_standard_config_directory_takes_precedence(self):
        alternate = self.home / "custom config"
        result = self.run_script(config_dir=alternate)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((alternate / "skills/교재").is_symlink())
        self.assertFalse((self.home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
