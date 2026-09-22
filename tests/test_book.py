"""단계별 통과 조건과 합본의 링크·원본 보존을 임시 책으로 검증한다."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("claude_book", REPO / "shared/orchestration/book.py")
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)


def document(path, metadata, body):
    header = "\n".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{header}\n---\n{body}\n", encoding="utf-8")


class BookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="claude-book-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "00-설계").mkdir()
        (self.root / "00-설계/설계서.md").write_text("# 학습 경로\n01 → 02\n", encoding="utf-8")
        (self.root / "목차.md").write_text("# 학습 목차\n1. 기초\n2. 응용\n", encoding="utf-8")
        self.bodies, self.summaries = {}, {}
        for no in ("01", "02"):
            document(self.contract(no), {"번호": no, "제목": f"제목 {no}", "슬러그": f"chapter-{no}",
                     "선수챕터": [] if no == "01" else ["01"], "목차항목": [str(int(no))],
                     "분량": "100자", "읽기시간": "1분", "계약버전": 1}, "## 학습 목표\n질문에 답한다.")
        for no in ("01", "02"):
            self.write_chapter(no)
        self.reviews()
        (self.root / "index.md").write_text(
            "# 테스트 책\n[기초](chapters/01-chapter-01.md)\n[응용](chapters/02-chapter-02.md)\n", encoding="utf-8")

    def contract(self, no):
        return self.root / f"00-설계/챕터계약/{no}.md"

    def chapter(self, no):
        return self.root / f"chapters/{no}-chapter-{no}.md"

    def write_chapter(self, no, text=None, summary=None):
        self.bodies[no] = text if text is not None else self.bodies.get(no, f"# 장 {no}\n\n## 연습\n본문입니다.")
        self.summaries[no] = summary if summary is not None else self.summaries.get(no, f"{no}의 학습 결과")
        book.ERR.clear()
        contracts, chapters, _ = book.load_book(self.root)
        receipt = book.input_hash(self.root, no, contracts, chapters)
        document(self.chapter(no), {"번호": no, "제목": f"제목 {no}", "계약버전": 1,
                 "입력해시": receipt, "요약": self.summaries[no], "이월제안": []}, self.bodies[no])

    def reviews(self, severity=None):
        contracts, chapters, _ = book.load_book(self.root)
        for no in ("01", "02"):
            for axis in ("정확성", "독자"):
                counts = {"S1": 0, "S2": 0, "S3": 0}
                issue = ""
                if severity and no == "01" and axis == "정확성":
                    counts[severity] = 1
                    issue = f"\n| {severity}-1 | {severity} | L2 | 결함 | 수정 |"
                document(self.root / f"검수/{no}-{axis}.md", {
                    "대상": self.chapter(no).relative_to(self.root).as_posix(),
                    "대상해시": book.sha256(self.chapter(no)), "계약해시": book.sha256(self.contract(no)),
                    "검수입력해시": book.review_input_hash(self.root, no, contracts, chapters),
                    "축": axis, "계약버전": 1, **counts}, "## 판정\n검수 결과" + issue)

    def run_book(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = book.main(list(args))
        return result, output.getvalue()

    def check(self, stage="final", *extra):
        return self.run_book("check", str(self.root), "--stage", stage, *extra)

    def test_valid_book_passes_each_stage_and_build(self):
        for stage in ("plan", "draft", "review", "final"):
            code, output = self.check(stage)
            self.assertEqual(code, 0, output)
        self.assertEqual(self.run_book("build", str(self.root))[0], 0)

    def test_plan_accepts_missing_drafts_but_review_and_build_do_not(self):
        self.chapter("02").unlink()
        self.assertEqual(self.check("plan")[0], 0)
        self.assertEqual(self.check("review")[0], 1)
        self.assertEqual(self.run_book("build", str(self.root))[0], 1)
        self.assertFalse((self.root / f"{self.root.name}.md").exists())

    def test_unreviewed_draft_never_passes_final(self):
        for path in (self.root / "검수").glob("*.md"):
            path.unlink()
        self.assertEqual(self.check("draft")[0], 0)
        self.assertEqual(self.check()[0], 1)

    def test_s1_blocks_but_s2_is_disclosed_without_blocking(self):
        self.reviews("S1")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("미해결 S1", output)
        self.reviews("S2")
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.assertIn("S2 1건 남음", output)

    def test_review_counter_cannot_hide_an_issue(self):
        self.reviews("S1")
        p = self.root / "검수/01-정확성.md"
        p.write_text(p.read_text().replace("S1: 1", "S1: 0"), encoding="utf-8")
        self.assertEqual(self.check()[0], 1)

    def test_review_after_edit_must_be_redone(self):
        self.write_chapter("02", text="# 수정된 장\n## 연습\n다른 본문")
        self.assertEqual(self.check("draft")[0], 0)
        self.assertEqual(self.check()[0], 1)
        self.reviews()
        self.assertEqual(self.check()[0], 0)

    def test_contract_edit_without_version_bump_is_stale(self):
        p = self.contract("02")
        p.write_text(p.read_text() + "\n추가된 질문\n", encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("입력해시", output)
        self.assertIn("계약 판본", output)

    def test_changed_predecessor_summary_invalidates_successor(self):
        self.write_chapter("01", summary="새 전제")
        self.reviews()
        code, output = self.check("review", "--chapter", "02")
        self.assertEqual(code, 1)
        self.assertIn("02장: 입력해시", output)

    def test_partial_check_does_not_require_unrelated_unwritten_chapters(self):
        self.chapter("02").unlink()
        self.assertEqual(self.check("review", "--chapter", "01")[0], 0)

    def test_predecessor_body_edit_invalidates_review_even_when_summary_is_unchanged(self):
        self.write_chapter("01", text="# 장 01\n완전히 달라진 설명")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("02-독자.md: 검수입력해시", output)

    def test_declared_forward_link_can_wait_until_final(self):
        self.write_chapter("01", text="# 장 01\n[후행](02-chapter-02.md#아직-없는-절)")
        self.reviews()
        self.chapter("02").unlink()
        code, output = self.check("review", "--chapter", "01")
        self.assertEqual(code, 0, output)
        self.assertIn("미집필 후행 링크", output)
        self.assertEqual(self.check()[0], 1)

    def test_report_target_axis_version_and_counts_are_required(self):
        p = self.root / "검수/01-정확성.md"
        original = p.read_text()
        for old, new in (("chapters/01-chapter-01.md", "chapters/02-chapter-02.md"),
                         ('축: "정확성"', '축: "독자"'), ("계약버전: 1", "계약버전: 2"),
                         ("S1: 0\n", ""), ("S2: 0", "S2: -1")):
            with self.subTest(new=new):
                p.write_text(original.replace(old, new), encoding="utf-8")
                self.assertEqual(self.check()[0], 1)
        p.write_text(original, encoding="utf-8")

    def test_duplicate_chapter_is_not_silently_overwritten(self):
        (self.root / "chapters/01-duplicate.md").write_bytes(self.chapter("01").read_bytes())
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("중복", output)

    def test_cycle_and_missing_toc_assignment_fail_plan(self):
        p = self.contract("01")
        p.write_text(p.read_text().replace("선수챕터: []", '선수챕터: ["02"]')
                     .replace('목차항목: ["1"]', "목차항목: []"), encoding="utf-8")
        code, output = self.check("plan")
        self.assertEqual(code, 1)
        self.assertIn("순환", output)
        self.assertIn("목차 1", output)

    def test_malformed_frontmatter_fails_cleanly(self):
        self.chapter("01").write_text("---\n번호: 01\n요약: |\n  여러 줄\n---\n본문", encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", output)

    def test_empty_review_body_fails(self):
        path = self.root / "검수/01-정확성.md"
        document(path, book.frontmatter(path), "")
        self.assertIn("리포트 본문이 비었다", self.check()[1])

    def test_final_requires_index_and_no_unresolved_markers(self):
        (self.root / "index.md").unlink()
        self.assertEqual(self.check()[0], 1)
        self.assertEqual(self.check("review")[0], 0)
        self.write_chapter("01", text="# 본문\n<!-- 확인 필요: 버전 -->")
        self.reviews()
        self.assertIn("확인 필요", self.check()[1])

    def test_build_preserves_code_and_rewrites_chapter_anchors_and_assets(self):
        (self.root / "assets").mkdir()
        (self.root / "assets/pic.png").write_bytes(b"fixture")
        example = "```md\n# 예제 제목\n[예제](missing.md)\n```"
        self.write_chapter("01", text="# 장 01\n## 연습\n"
                           "[다음](02-chapter-02.md#연습-1)\n![그림](../assets/pic.png)\n"
                           "`[인라인 예제](missing.md)`\n" + example)
        self.write_chapter("02", text="# 장 02\n## 연습\n본문\n## 연습\n반복 제목\n[앞](01-chapter-01.md#연습)")
        self.reviews()
        out = self.root / "combined.md"
        code, output = self.run_book("build", str(self.root), str(out))
        self.assertEqual(code, 0, output)
        result = out.read_text()
        for expected in (example, "`[인라인 예제](missing.md)`", "](#ch02-연습-1)",
                         "](#ch01-연습)", 'id="ch02-연습-1"', "](assets/pic.png)"):
            self.assertIn(expected, result)
        self.assertEqual(self.run_book("build", str(self.root), str(out))[0], 0)

    def test_build_never_overwrites_source_or_existing_user_file(self):
        custom = self.root / "notes.md"
        custom.write_text("사용자 메모", encoding="utf-8")
        for path in (custom, self.chapter("01"), self.root / "index.md"):
            original = path.read_bytes()
            self.assertEqual(self.run_book("build", str(self.root), str(path))[0], 1)
            self.assertEqual(path.read_bytes(), original)

    def test_bad_links_block_build_but_examples_inside_code_do_not(self):
        self.write_chapter("02", text="# 장\n[깨진 링크](missing.md)")
        self.reviews()
        self.assertEqual(self.run_book("build", str(self.root))[0], 1)


if __name__ == "__main__":
    unittest.main()
