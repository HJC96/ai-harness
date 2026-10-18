"""훅 스크립트를 실제 프로세스로 돌려 차단·허용·기록·종료 점검을 검증한다."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "shared/orchestration/hook.py"
BOOK = REPO / "shared/orchestration/book.py"
SAMPLE = REPO / "tests/fixtures/견본"


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ai-harness-hook-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / "book"
        shutil.copytree(SAMPLE, self.root)
        (self.root / ".교재상태.json").write_text("{}", encoding="utf-8")

    def hook(self, mode, role, **data):
        data.setdefault("session_id", "s1")
        data.setdefault("cwd", str(self.base))
        return subprocess.run([sys.executable, str(HOOK), mode, role], input=json.dumps(data),
                              text=True, capture_output=True, check=False)

    def write(self, role, rel, tool="Write", **extra):
        path = rel if rel.startswith("/") else str(self.root / rel)
        return self.hook("pre", role, tool_name=tool, tool_input={"file_path": path}, **extra)

    def log(self):
        path = self.root / ".교재기록.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_blocks_only_writes_that_break_review_independence(self):
        cases = [
            ("main", "chapters/02-bigdecimal-표현.md", 2),
            ("main", "검수/02-정확성.md", 2),
            ("main", "00-설계/챕터계약/02.md", 2),
            ("main", ".교재상태.json", 0),
            ("main", "미확인-수락.md", 0),
            ("technical-reviewer", "검수/02-정확성.md", 0),
            ("technical-reviewer", "chapters/02-bigdecimal-표현.md", 2),
            ("learner-advocate", ".교재상태.json", 2),
            ("learner-advocate", "검수", 2),
            ("chapter-writer", "chapters/02-bigdecimal-표현.md", 0),
            ("chapter-writer", "검수/02-독자.md", 2),
            ("learning-editor", "index.md", 0),
            ("learning-editor", "미확인-수락.md", 2),
            ("curriculum-architect", "00-설계/설계서.md", 0),
            ("curriculum-architect", ".교재기록.jsonl", 2),
        ]
        for role, rel, code in cases:
            with self.subTest(role=role, rel=rel):
                result = self.write(role, rel)
                self.assertEqual(result.returncode, code, result.stderr)
                if code:
                    self.assertIn(rel, result.stderr)
        blocked = [e for e in self.log() if e["사건"] == "차단"]
        self.assertEqual(len(blocked), sum(1 for *_, code in cases if code))
        self.assertTrue(all(e["사유"] for e in blocked))
        self.assertEqual(blocked[0]["역할"], "지휘자")

    def test_relative_paths_and_edit_tools_resolve_against_cwd(self):
        result = self.hook("pre", "technical-reviewer", tool_name="Edit", cwd=str(self.root),
                           tool_input={"file_path": "chapters/../chapters/01-double-오차.md"})
        self.assertEqual(result.returncode, 2)
        result = self.hook("pre", "main", tool_name="NotebookEdit",
                           tool_input={"notebook_path": str(self.root / "chapters/x.ipynb")})
        self.assertEqual(result.returncode, 2)

    def test_does_nothing_outside_a_book_workspace(self):
        (self.root / ".교재상태.json").unlink()
        self.assertEqual(self.write("main", "chapters/02-bigdecimal-표현.md").returncode, 0)
        self.assertEqual(self.write("technical-reviewer", str(self.base / "Scratch.java")).returncode, 0)
        self.assertEqual(self.log(), [])

    def test_main_rules_skip_tool_calls_made_by_a_subagent(self):
        result = self.write("main", "chapters/02-bigdecimal-표현.md", agent_type="chapter-writer")
        self.assertEqual(result.returncode, 0)
        result = self.hook("post", "main", tool_name="Write", agent_type="chapter-writer",
                           tool_input={"file_path": str(self.root / "chapters/02-bigdecimal-표현.md")})
        self.assertEqual(self.log(), [])

    def test_post_records_each_write_in_the_workspace(self):
        self.hook("post", "chapter-writer", tool_name="Edit", agent_id="a1", agent_type="chapter-writer",
                  tool_input={"file_path": str(self.root / "chapters/02-bigdecimal-표현.md")})
        self.hook("post", "chapter-writer", tool_name="Write",
                  tool_input={"file_path": str(self.base / "elsewhere.md")})
        [entry] = self.log()
        self.assertEqual((entry["역할"], entry["에이전트"], entry["사건"], entry["도구"], entry["경로"]),
                         ("chapter-writer", "a1", "쓰기", "Edit", "chapters/02-bigdecimal-표현.md"))

    def test_allows_only_plain_book_commands(self):
        def decision(role, command):
            out = self.hook("pre", role, tool_name="Bash", tool_input={"command": command}).stdout
            return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else None
        root = str(self.root)
        self.assertEqual(decision("technical-reviewer", f"python3 {BOOK} review-inputs {root} 02 정확성"), "allow")
        self.assertEqual(decision("main", f'python3 {BOOK} check "{root}" --stage draft --chapter 02'), "allow")
        self.assertEqual(decision("main", f"python3 {BOOK} build {root}"), "allow")
        self.assertIsNone(decision("chapter-writer", f"python3 {BOOK} build {root}"))
        self.assertIsNone(decision("main", f"python3 {BOOK} check {root}; rm -rf {root}"))
        self.assertIsNone(decision("main", f"python3 {BOOK} hash $(cat secret)"))
        self.assertIsNone(decision("main", f"python3 {HOOK} check {root}"))
        self.assertIsNone(decision("main", f"git commit -m x"))

    def test_stop_checks_only_what_the_worker_wrote(self):
        chapter = self.root / "chapters/02-bigdecimal-표현.md"
        chapter.write_text(chapter.read_text(encoding="utf-8") + "\n덧붙인 문장\n", encoding="utf-8")
        transcript = self.base / "agent.jsonl"
        lines = [{"type": "assistant", "message": {"content": [
                     {"type": "tool_use", "name": "Edit", "input": {"file_path": str(chapter)}}]}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}]
        transcript.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines), encoding="utf-8")

        result = self.hook("stop", "chapter-writer", agent_id="a1", agent_transcript_path=str(transcript))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.log()[-1]["사건"], "종료점검")
        self.assertEqual(self.log()[-1]["결과"], "오류 0 · 경고 0")
        self.assertEqual(result.stdout.strip(), "")

        result = self.hook("stop", "technical-reviewer", agent_id="a2", agent_transcript_path=str(transcript))
        self.assertEqual(result.stdout.strip(), "")  # 검수자가 쓴 리포트가 없으면 점검할 것이 없다
        report = self.root / "검수/02-정확성.md"
        lines[0]["message"]["content"][0]["input"]["file_path"] = str(report)
        transcript.write_text(json.dumps(lines[0], ensure_ascii=False), encoding="utf-8")
        result = self.hook("stop", "technical-reviewer", agent_id="a2", agent_transcript_path=str(transcript))
        message = json.loads(result.stdout)["systemMessage"]
        self.assertIn("02-정확성.md: 검수한 판본과 현재 원고가 다르다", message)
        self.assertNotIn("02-독자.md", message)
        self.assertEqual(self.log()[-1]["결과"].split(" · ")[0], "오류 1")

        # 설계 검수 리포트를 쓴 검수자는 design 단계로, 자기 리포트의 메시지만 본다.
        contract = self.root / "00-설계/챕터계약/02.md"
        contract.write_text(contract.read_text(encoding="utf-8") + "\n덧붙인 줄\n", encoding="utf-8")
        lines[0]["message"]["content"][0]["input"]["file_path"] = str(self.root / "검수/설계-독자.md")
        transcript.write_text(json.dumps(lines[0], ensure_ascii=False), encoding="utf-8")
        result = self.hook("stop", "learner-advocate", agent_id="a3", agent_transcript_path=str(transcript))
        message = json.loads(result.stdout)["systemMessage"]
        self.assertIn("설계-독자.md: 검수한 설계와 현재 00-설계가 다르다", message)
        self.assertNotIn("설계-정확성.md", message)

    def test_stop_also_checks_assigned_files_written_outside_write_and_edit(self):
        # 9번 한 바퀴: 편집자가 챕터를 Bash로 고쳐 기록에는 index.md만 남고 종료 점검도 비었다.
        chapter = self.root / "chapters/02-bigdecimal-표현.md"
        untouched = self.root / "chapters/01-double-오차.md"
        message = (f"작업 ID:    edit-r1\n역할:       learning-editor\n작업 공간:  {self.root}\n"
                   "쓸 수 있는 파일: chapters/01-double-오차.md, chapters/02-bigdecimal-표현.md (연결·표기만),\n"
                   "            index.md\n완료 조건:  draft 통과")
        transcript = self.base / "editor.jsonl"
        lines = [{"type": "user", "timestamp": "2026-01-01T00:00:00.000Z", "message": {"content": message}},
                 {"type": "assistant", "message": {"content": [
                     {"type": "tool_use", "name": "Write", "input": {"file_path": str(self.root / "index.md")}}]}}]
        transcript.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in lines), encoding="utf-8")
        os.utime(untouched, (0, 0))  # 작업 전부터 그대로인 배정 파일
        chapter.write_text(chapter.read_text(encoding="utf-8").replace("이제 값은 정확하다.", "이제 값은 늘 정확하다."),
                           encoding="utf-8")

        result = self.hook("stop", "learning-editor", agent_id="a9", agent_transcript_path=str(transcript))
        self.assertEqual(result.returncode, 0)
        unseen = [e for e in self.log() if e["사건"] == "쓰기"]
        self.assertEqual([(e["도구"], e["경로"]) for e in unseen], [("미상", "chapters/02-bigdecimal-표현.md")])
        message = json.loads(result.stdout)["systemMessage"]
        self.assertIn("Write·Edit 밖에서 바뀐 배정 파일: chapters/02-bigdecimal-표현.md", message)
        self.assertNotIn("01-double-오차.md", message)

    def test_hook_failures_never_block(self):
        result = subprocess.run([sys.executable, str(HOOK), "pre", "main"], input="not json",
                                text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)
        result = self.hook("stop", "chapter-writer", agent_transcript_path=str(self.base / "없음.jsonl"))
        self.assertEqual(result.returncode, 0)
        self.assertNotEqual(self.hook("pre", "nobody", tool_name="Write").returncode, 2)

    def test_frontmatter_command_is_a_no_op_when_not_installed(self):
        command = ('h="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/orchestration/hook.py"; '
                   '[ ! -f "$h" ] || python3 "$h" pre main')
        payload = json.dumps({"tool_name": "Write", "cwd": str(self.base),
                              "tool_input": {"file_path": str(self.root / "검수/02-정확성.md")}})
        run = lambda config: subprocess.run(
            ["bash", "-c", command], input=payload, text=True, capture_output=True, check=False,
            env={"PATH": os.environ["PATH"], "HOME": str(self.base), "CLAUDE_CONFIG_DIR": str(config)})
        self.assertEqual(run(self.base / "missing").returncode, 0)
        (self.base / "cfg/orchestration").mkdir(parents=True)
        (self.base / "cfg/orchestration/hook.py").symlink_to(HOOK)
        self.assertEqual(run(self.base / "cfg").returncode, 2)


if __name__ == "__main__":
    unittest.main()
