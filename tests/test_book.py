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


DESIGN = """# 테스트 책 — 설계서

## 학습 경로
01 → 02

## 의존성 그래프
| 레벨 | 챕터 | 동시 집필 |
|---|---|---|
| 0 | 01 | — |
| 1 | 02 | — |

## 관통 사례
01장: 정상 · 02장: 실패

## 용어집
| 용어 | 표기 | 최초 정의 챕터 |
|---|---|---|
| 기초 | 기초 | 01 |

## 원래 목차에서 바꾼 것
| 바꾼 것 | 원래 | 이유 |
|---|---|---|
| 없음 | — | 순서가 이미 맞다 |

## 챕터 목록
01 기초 · 02 응용
"""


def contract_body(no):
    other = "02" if no == "01" else "01"
    return (f"## 한 줄 목표\n질문에 답한다.\n\n## 다 읽으면 답할 수 있는 질문\n1. 무엇인가?\n2. 왜인가?\n\n"
            f"## 다루는 것\n- 연습\n\n## 다루지 않는 것\n- 다른 장의 내용 → **{other}장 소유**\n\n"
            f"## 관통 사례에서 쓰는 장면\n{no}장 장면\n\n## 필수 포함\n- 코드 예시: 0개\n\n"
            f"## 이어받을 문장\n앞의 문제\n\n## 넘길 것\n다음 문제\n\n"
            f"## 이 챕터에서 처음 정의하는 용어\n- 없음\n\n## 근거 확인 필요 항목\n- 없음")


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
        (self.root / "00-설계/설계서.md").write_text(DESIGN, encoding="utf-8")
        (self.root / "목차.md").write_text("# 학습 목차\n1. 기초\n2. 응용\n", encoding="utf-8")
        self.bodies, self.summaries = {}, {}
        for no in ("01", "02"):
            document(self.contract(no), {"번호": no, "제목": f"제목 {no}", "슬러그": f"chapter-{no}",
                     "선수챕터": [] if no == "01" else ["01"], "목차항목": [str(int(no))],
                     "분량": "1~300자", "읽기시간": "1분", "계약버전": 1}, contract_body(no))
        for axis in ("정확성", "독자"):
            self.design_report(axis)
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
        self.bodies[no] = text if text is not None else self.bodies.get(
            no, f"# 장 {no}\n\n## 연습\n본문입니다.\n\n## 응용\n본문입니다.\n\n## 다 읽고 나면\n정리")
        self.summaries[no] = summary if summary is not None else self.summaries.get(no, f"{no}의 학습 결과")
        book.ERR.clear()
        contracts, chapters, _ = book.load_book(self.root)
        receipt = book.input_hash(self.root, no, contracts, chapters)
        document(self.chapter(no), {"번호": no, "제목": f"제목 {no}", "계약버전": 1,
                 "입력해시": receipt, "요약": self.summaries[no], "이월제안": []}, self.bodies[no])

    def reviews(self, severity=None):
        for no in ("01", "02"):
            for axis in ("정확성", "독자"):
                issues = [(f"{severity}-1", severity)] if severity and no == "01" and axis == "정확성" else []
                self.report(no, axis, issues)

    @staticmethod
    def findings(issues, unknowns, owner):
        """지적 표와 미확인 절. issues는 (ID, 심각도) 또는 (ID, 심각도, 귀속)."""
        counts = {"S1": 0, "S2": 0, "S3": 0}
        for issue in issues:
            counts[issue[1]] += 1
        rows = "".join(f"| {i[0]} | {i[1]} | {i[2] if len(i) > 2 else owner} | L2 | 결함 | 수정 |\n"
                       for i in issues)
        return counts, (f"## 판정\n{book.verdict(counts)}\n\n"
                        "| ID | 심각도 | 귀속 | 위치 | 무엇이 문제인가 | 제안 |\n|---|---|---|---|---|---|\n" + rows
                        + "\n## 미확인\n" + ("".join(f"| {u} | L2 | 기본값 | 문서 없음 | 공식 문서 |\n"
                                                    for u in unknowns) or "없음\n"))

    def report(self, no, axis, issues=(), unknowns=(), earlier=(), version=1, trigger=None):
        """현재 판본의 리포트. earlier는 그 앞 회차의 (계기, 대상해시, 계약버전, 미해결 S1) 목록."""
        contracts, chapters, _ = book.load_book(self.root)
        counts, text = self.findings(issues, unknowns, "원고")
        rows = [(*row, "재집필 필요" if row[3] else "통과") for row in earlier]
        rows.append((trigger or ("재집필" if earlier else "첫 검수"), book.sha256(self.chapter(no)), version,
                     [i[0] for i in issues if i[1] == "S1"], book.verdict(counts)))
        history = "".join(f"| {n} | {trigger} | {digest} | {ver} | {result} | {', '.join(s1) or '없음'} |\n"
                          for n, (trigger, digest, ver, s1, result) in enumerate(rows, 1))
        text += ("\n## 검수 이력\n| 회차 | 계기 | 대상해시 | 계약버전 | 판정 | 미해결 S1 |\n"
                 "|---|---|---|---|---|---|\n" + history)
        path = self.root / f"검수/{no}-{axis}.md"
        document(path, {
            "대상": self.chapter(no).relative_to(self.root).as_posix(),
            "대상해시": book.sha256(self.chapter(no)), "계약해시": book.sha256(self.contract(no)),
            "검수입력해시": book.review_input_hash(self.root, no, contracts, chapters, axis),
            "축": axis, "계약버전": version, **counts, "미확인": len(unknowns)}, text)
        return path

    def design_report(self, axis, issues=(), unknowns=(), earlier=()):
        """현재 00-설계의 설계 검수 리포트. earlier는 앞 회차의 (계기, 대상해시, 미해결 S1) 목록."""
        counts, text = self.findings(issues, unknowns, "계약")
        digest = book.tree_hash(self.root / "00-설계")
        rows = [(*row, "재집필 필요" if row[2] else "통과") for row in earlier]
        rows.append(("재설계" if earlier else "첫 검수", digest, [i[0] for i in issues if i[1] == "S1"],
                     book.verdict(counts)))
        text += ("\n## 검수 이력\n| 회차 | 계기 | 대상해시 | 판정 | 미해결 S1 |\n|---|---|---|---|---|\n"
                 + "".join(f"| {n} | {trigger} | {d} | {result} | {', '.join(s1) or '없음'} |\n"
                           for n, (trigger, d, s1, result) in enumerate(rows, 1)))
        path = self.root / f"검수/설계-{axis}.md"
        document(path, {"대상": "00-설계", "대상해시": digest, "축": axis, **counts, "미확인": len(unknowns)}, text)
        return path

    def run_book(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = book.main(list(args))
        return result, output.getvalue()

    def check(self, stage="final", *extra):
        return self.run_book("check", str(self.root), "--stage", stage, *extra)

    def tally(self, no):
        code, output = self.run_book("tally", str(self.root), "--chapter", no)
        self.assertEqual(code, 0, output)
        return json.loads(output)[no]

    def test_valid_book_passes_each_stage_and_build(self):
        for stage in ("plan", "design", "draft", "review", "final"):
            code, output = self.check(stage)
            self.assertEqual(code, 0, output)
            self.assertNotIn("경고", output)
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
        # 정확성 판정은 선수 본문에 기대지 않는다.
        self.assertNotIn("02-정확성.md", output)

    def test_contract_edit_invalidates_only_the_accuracy_review_inputs(self):
        p = self.contract("02")
        p.write_text(p.read_text() + "\n추가된 질문\n", encoding="utf-8")
        output = self.check("review", "--chapter", "02")[1]
        self.assertIn("02-정확성.md: 검수입력해시", output)
        self.assertNotIn("02-독자.md: 검수입력해시", output)

    def test_review_input_hash_is_versioned_and_differs_by_axis(self):
        contracts, chapters, _ = book.load_book(self.root)
        values = {axis: book.review_input_hash(self.root, "02", contracts, chapters, axis)
                  for axis in ("정확성", "독자")}
        self.assertNotEqual(values["정확성"], values["독자"])
        for value in values.values():
            self.assertRegex(value, r"^v2:[0-9a-f]{64}$")
        code, output = self.run_book("review-inputs", str(self.root), "02", "독자")
        self.assertEqual((code, output.strip()), (0, values["독자"]))
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.run_book("review-inputs", str(self.root), "02")

    def test_unversioned_review_input_hash_requires_rereview(self):
        for axis in ("정확성", "독자"):
            with self.subTest(axis):
                p = self.root / f"검수/01-{axis}.md"
                original = p.read_text()
                p.write_text(original.replace('검수입력해시: "v2:', '검수입력해시: "'), encoding="utf-8")
                code, output = self.check()
                self.assertEqual(code, 1)
                self.assertIn("v1 값", output)
                p.write_text(original, encoding="utf-8")

    def test_review_input_hash_cannot_be_copied_across_axes(self):
        source, target = self.root / "검수/01-독자.md", self.root / "검수/01-정확성.md"
        value = book.frontmatter(source)["검수입력해시"]
        target.write_text(target.read_text().replace(book.frontmatter(target)["검수입력해시"], value),
                          encoding="utf-8")
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("01-정확성.md: 검수입력해시", output)

    def test_review_history_must_match_the_current_report(self):
        p = self.root / "검수/01-정확성.md"
        original = p.read_text()
        digest = book.sha256(self.chapter("01"))
        for old, new in (("## 검수 이력", "## 이력"), ("| 1 | 첫 검수 |", "| 2 | 첫 검수 |"),
                         ("| 첫 검수 |", "| 다시 봄 |"), (f"{digest} | 1 |", f"{'0' * 64} | 1 |"),
                         (f"{digest} | 1 |", f"{digest} | 2 |"), ("| 통과 | 없음 |", "| 수정 권고 | 없음 |"),
                         ("| 통과 | 없음 |", "| 통과 | S1-1 |"), ("## 판정\n통과", "## 판정\n수정 권고")):
            with self.subTest(new=new):
                p.write_text(original.replace(old, new, 1), encoding="utf-8")
                self.assertEqual(self.check("review")[0], 1)
        p.write_text(original.replace("## 검수 이력", "## 이력"), encoding="utf-8")
        self.assertEqual(self.run_book("tally", str(self.root))[0], 1)

    def test_same_finding_surviving_two_rewrites_blocks_the_chapter(self):
        a, b = "a" * 64, "b" * 64
        self.report("01", "정확성", [("S1-1", "S1")], earlier=[("첫 검수", a, 1, ["S1-1"])])
        self.assertEqual(self.tally("01"), {"계약버전": "1", "재집필": 1, "편집": 0,
                                            "열린지적": {"01/정확성/S1-1": 1}, "계약귀속": [], "계약대기": [], "막힘": []})
        self.report("01", "정확성", [("S1-1", "S1")],
                    earlier=[("첫 검수", a, 1, ["S1-1"]), ("재집필", b, 1, ["S1-1"])])
        result = self.tally("01")
        self.assertEqual(result["열린지적"], {"01/정확성/S1-1": 2})
        self.assertIn("01/정확성/S1-1", result["막힘"][0])
        self.assertIn("blocked", self.check("review")[1])

    def test_only_rewrites_of_a_new_version_count_as_survival(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        self.report("01", "정확성", [("S1-1", "S1")], earlier=[
            ("첫 검수", a, 1, ["S1-1"]), ("편집", b, 1, ["S1-1"]), ("입력 변경", c, 1, ["S1-1"]),
            ("재집필", c, 1, ["S1-1"])])
        result = self.tally("01")
        self.assertEqual((result["열린지적"], result["재집필"], result["편집"]), ({"01/정확성/S1-1": 1}, 2, 1))

    def test_contract_revision_restarts_the_count(self):
        a, b, c = "a" * 64, "b" * 64, "c" * 64
        p = self.contract("01")
        p.write_text(p.read_text().replace("계약버전: 1", "계약버전: 2"), encoding="utf-8")
        self.report("01", "정확성", [("S1-1", "S1")], version=2, earlier=[
            ("첫 검수", a, 1, ["S1-1"]), ("재집필", b, 1, ["S1-1"]), ("재집필", c, 1, ["S1-1"])])
        self.assertEqual(self.tally("01"), {"계약버전": "2", "재집필": 1, "편집": 0,
                                            "열린지적": {"01/정확성/S1-1": 0}, "계약귀속": [], "계약대기": [], "막힘": []})

    def test_four_rewrites_with_new_s1_each_time_block_as_a_contract_problem(self):
        h = [c * 64 for c in "abcd"]
        earlier = [("첫 검수", h[0], 1, ["S1-1"])] + [("재집필", h[i], 1, [f"S1-{i + 1}"]) for i in (1, 2, 3)]
        self.report("01", "정확성", [("S1-5", "S1")], earlier=earlier)
        # 두 축 이력의 같은 판본은 한 번만 센다.
        self.report("01", "독자", earlier=[(t, d, v, []) for t, d, v, _ in earlier])
        result = self.tally("01")
        self.assertEqual(result["재집필"], 4)
        self.assertEqual(result["열린지적"], {"01/정확성/S1-5": 0})
        self.assertEqual(len(result["막힘"]), 1)
        self.assertIn("재집필 4회", result["막힘"][0])

    def test_design_review_gates_writing_and_is_invalidated_by_any_design_change(self):
        for p in (self.root / "chapters").glob("*.md"):
            p.unlink()
        for p in (self.root / "검수").glob("[0-9]*.md"):
            p.unlink()
        self.assertEqual(self.check("design")[0], 0)
        contract = self.contract("02")
        contract.write_text(contract.read_text() + "\n덧붙인 줄\n", encoding="utf-8")
        self.assertEqual(self.check("plan")[0], 0)
        code, output = self.check("design")
        self.assertEqual(code, 1)
        self.assertIn("설계-정확성.md: 검수한 설계와 현재 00-설계가 다르다", output)
        self.assertIn("설계-독자.md: 검수한 설계와 현재 00-설계가 다르다", output)
        for axis in ("정확성", "독자"):
            self.design_report(axis)
        self.assertEqual(self.check("design")[0], 0)
        (self.root / "검수/설계-독자.md").unlink()
        self.assertIn("정확성·독자 리포트가 각각", self.check("design")[1])
        for p in (self.root / "검수").glob("설계-*.md"):
            p.unlink()
        code, output = self.check("design")
        self.assertEqual(code, 1)
        self.assertIn("설계 검수 리포트가 없다", output)

    def test_books_written_before_design_review_only_warn(self):
        for p in (self.root / "검수").glob("설계-*.md"):
            p.unlink()
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.assertIn("! 설계 검수 리포트가 없다", output)

    def test_design_s1_blocks_and_s2_or_unknown_only_warns(self):
        self.design_report("독자", [("S1-1", "S1")])
        code, output = self.check("design")
        self.assertEqual(code, 1)
        self.assertIn("설계-독자.md: 미해결 S1 S1-1", output)
        self.assertEqual(self.check("draft")[0], 1)
        self.design_report("독자", [("S2-1", "S2")], unknowns=["U-1"])
        code, output = self.check("design")
        self.assertEqual(code, 0, output)
        self.assertIn("설계-독자.md: S2 1건 남음", output)
        self.assertIn("설계-독자.md: 미확인 1건", output)

    def test_design_history_has_no_contract_version_and_only_design_triggers(self):
        p = self.design_report("정확성")
        original = p.read_text()
        for old, new in (("| 회차 | 계기 | 대상해시 | 판정 |", "| 회차 | 계기 | 대상해시 | 계약버전 | 판정 |"),
                         ("| 첫 검수 |", "| 재집필 |"), ("대상: \"00-설계\"", "대상: \"chapters\"")):
            with self.subTest(new=new):
                p.write_text(original.replace(old, new, 1), encoding="utf-8")
                self.assertEqual(self.check("design")[0], 1)
        p.write_text(original, encoding="utf-8")
        self.assertEqual(self.check("design")[0], 0)

    def test_attribution_is_required_and_design_findings_belong_to_the_contract(self):
        self.report("01", "독자", [("S2-1", "S2", "작가")])
        self.assertIn("S2-1의 귀속은 원고 또는 계약이다", self.check("review")[1])
        self.report("01", "독자")
        self.design_report("독자", [("S2-1", "S2", "원고")])
        self.assertIn("S2-1의 귀속은 계약이다", self.check("design")[1])

    def test_contract_owned_s1_is_routed_to_the_architect(self):
        self.report("01", "정확성", [("S1-1", "S1", "원고"), ("S1-2", "S1", "계약")])
        self.assertEqual(self.tally("01")["계약귀속"], ["01/정확성/S1-2"])
        code, output = self.check("review")
        self.assertEqual(code, 1)
        self.assertIn("계약 귀속 S1-2은 설계자에게", output)

    def test_contract_owned_s2_s3_wait_for_the_next_contract_revision(self):
        self.report("01", "정확성", [("S2-1", "S2", "계약"), ("S3-1", "S3", "원고"), ("S3-2", "S3", "계약")])
        tally = self.tally("01")
        self.assertEqual((tally["계약귀속"], tally["계약대기"]), ([], ["01/정확성/S2-1", "01/정확성/S3-2"]))
        self.assertEqual(self.check("review")[0], 0)

    def test_design_s2_warnings_are_not_repeated_while_drafting(self):
        self.design_report("독자", [("S2-1", "S2")])
        for stage, shown in (("design", True), ("draft", False), ("review", False), ("final", True)):
            with self.subTest(stage=stage):
                self.assertEqual("설계-독자.md: S2 1건 남음" in self.check(stage)[1], shown)

    def test_axis_option_hides_the_other_axis_report(self):
        self.report("01", "정확성", [("S2-1", "S2")])
        self.report("01", "독자", [("S3-1", "S3")])
        self.design_report("정확성", [("S2-1", "S2")])
        mine = self.check("review", "--axis", "독자")[1]
        self.assertIn("01-독자.md: S3", mine)
        self.assertNotIn("정확성", mine)
        self.assertNotIn("설계-독자.md", self.check("design", "--axis", "정확성")[1])
        self.assertIn("설계-정확성.md: S2", self.check("design", "--axis", "정확성")[1])

    def test_axis_option_keeps_the_result_when_only_the_other_axis_fails(self):
        self.report("01", "정확성", [("S1-1", "S1")])
        code, out = self.check("review", "--axis", "독자")
        self.assertEqual(code, 1)
        self.assertNotIn("S1-1", out)
        self.assertNotIn("통과.", out)

    def test_same_design_finding_surviving_two_redesigns_blocks_the_book(self):
        a, b = "a" * 64, "b" * 64
        self.design_report("정확성", [("S1-1", "S1")], earlier=[("첫 검수", a, ["S1-1"])])
        code, output = self.run_book("tally", str(self.root))
        self.assertEqual(json.loads(output)["설계"], {"재설계": 1, "열린지적": {"설계/정확성/S1-1": 1}, "막힘": []})
        self.design_report("정확성", [("S1-1", "S1")],
                           earlier=[("첫 검수", a, ["S1-1"]), ("재설계", b, ["S1-1"])])
        design = json.loads(self.run_book("tally", str(self.root))[1])["설계"]
        self.assertIn("설계/정확성/S1-1", design["막힘"][0])
        self.assertIn("설계: 상한 도달", self.check("design")[1])
        # 챕터를 고르면 설계는 세지 않는다.
        self.assertNotIn("설계", json.loads(self.run_book("tally", str(self.root), "--chapter", "01")[1]))

    def test_directory_hash_covers_paths_and_content_but_not_dotfiles(self):
        design = self.root / "00-설계"
        code, output = self.run_book("hash", str(design))
        self.assertEqual((code, output.strip()), (0, book.tree_hash(design)))
        before = book.tree_hash(design)
        (design / ".DS_Store").write_bytes(b"x")
        self.assertEqual(book.tree_hash(design), before)
        (design / "메모.md").write_text("설계 메모", encoding="utf-8")
        self.assertNotEqual(book.tree_hash(design), before)

    def test_unverified_fact_blocks_final_until_the_user_accepts_that_version(self):
        p = self.report("01", "정확성", unknowns=["U-1"])
        code, output = self.check("review")
        self.assertEqual(code, 0, output)
        self.assertIn("미확인 1건", output)
        code, output = self.check()
        self.assertEqual(code, 1)
        self.assertIn("01-정확성.md: 미확인 U-1", output)
        accept = self.root / "미확인-수락.md"
        table = "# 미확인 수락\n\n| 추적 키 | 대상해시 | 일시 | 사용자 답 |\n|---|---|---|---|\n"
        row = '| 01/정확성/U-1 | {} | 2026-10-18T10:00:00+09:00 | "그대로 두자" |\n'
        for digest, expected in (("0" * 64, 1), ("abc", 1), (book.sha256(self.chapter("01")), 0)):
            with self.subTest(digest=digest):
                accept.write_text(table + row.format(digest), encoding="utf-8")
                self.assertEqual(self.check()[0], expected)
        p.write_text(p.read_text().replace("미확인: 1", "미확인: 0"), encoding="utf-8")
        self.assertIn("`미확인` 개수", self.check("review")[1])
        # 수락은 판본에 대한 것이다. 원고가 바뀌면 같은 ID라도 다시 묻는다.
        self.write_chapter("01", text="# 장 01\n## 연습\n고친 본문")
        self.reviews()
        self.report("01", "정확성", unknowns=["U-1"])
        self.assertIn("수락되지 않았다", self.check()[1])

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

    def test_intake_gate_checks_the_received_toc_and_state(self):
        code, output = self.check("intake")
        self.assertEqual(code, 1)
        self.assertIn("목차-원문.md", output)
        (self.root / "목차-원문.md").write_text("기초\n응용\n", encoding="utf-8")
        state = {"책": "테스트 책", "출력경로": "./book", "목차원본": "./목차-원문.md", "독자": "실무 4년차",
                 "깊이": "표준", "phase": 0, "챕터": [], "갱신": "2026-10-18T10:00:00+09:00"}
        path = self.root / ".교재상태.json"
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        code, output = self.check("intake")
        self.assertEqual(code, 0, output)
        for change, expected in (({"깊이": "보통"}, "`깊이`"), ({"phase": "0"}, "`phase`"),
                                 ({"목차원본": "./없음.md"}, "`목차원본`"), ({"독자": ""}, "`독자`")):
            with self.subTest(change=change):
                path.write_text(json.dumps({**state, **change}, ensure_ascii=False), encoding="utf-8")
                code, output = self.check("intake")
                self.assertEqual(code, 1)
                self.assertIn(expected, output)
        path.write_text(json.dumps({k: v for k, v in state.items() if k != "갱신"}, ensure_ascii=False),
                        encoding="utf-8")
        self.assertIn("`갱신` 누락", self.check("intake")[1])
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        (self.root / "목차.md").write_text("# 학습 목차\n1. 기초\n1. 응용\n", encoding="utf-8")
        self.assertIn("번호 1이 겹친다", self.check("intake")[1])
        # 접수 게이트는 계약 전에 돈다.
        for path in (self.root / "00-설계/챕터계약").glob("*.md"):
            path.unlink()
        (self.root / "목차.md").write_text("# 학습 목차\n1. 기초\n2. 응용\n", encoding="utf-8")
        self.assertEqual(self.check("intake")[0], 0)

    def test_design_checklist_fails_plan_before_drafts_and_warns_after(self):
        def replace(path, old, new):
            text = path.read_text(encoding="utf-8")
            self.assertIn(old, text)
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
        design = self.root / "00-설계/설계서.md"
        breaks = (
            (self.contract("02"), "2. 왜인가?\n", "", "질문은 번호를 붙인 줄로 2~3개다"),
            (self.contract("02"), "1. 무엇인가?", "1. 무엇인가?\n3. 어디인가?\n4. 언제인가?", "지금 4개"),
            (self.contract("01"), "→ **02장 소유**", "→ 뒤에서 다룬다", "소유 챕터 번호가 없다"),
            (self.contract("01"), "→ **02장 소유**", "→ **07장 소유**", "소유 챕터 07장"),
            (self.contract("01"), "## 넘길 것\n다음 문제", "## 넘길 것\n", "「넘길 것」 절이 없거나 비었다"),
            (self.contract("01"), '분량: "1~300자"', '분량: "적당히"', "`분량`은"),
            (design, "| 1 | 02 | — |", "| 0 | 02 | — |", "02장은 레벨 0인데"),
            (design, "| 1 | 02 | — |", "", "레벨 표에 02장이 없다"),
            (design, "| 기초 | 기초 | 01 |", "| 기초 | 기초 | 09 |", "용어집 행"),
            (design, "| 순서가 이미 맞다 |", "|  |", "이유가 없다"),
            (design, "## 관통 사례\n", "## 사례\n", "「관통 사례」 절이 없거나 비었다"),
        )
        drafts = {no: self.chapter(no).read_bytes() for no in ("01", "02")}
        for no in drafts:
            self.chapter(no).unlink()
        self.assertEqual(self.check("plan")[0], 0)
        for path, old, new, expected in breaks:
            with self.subTest(expected=expected):
                original = path.read_text(encoding="utf-8")
                replace(path, old, new)
                code, output = self.check("plan")
                self.assertEqual(code, 1)
                self.assertIn(expected, output)
                # 원고가 생긴 책은 이 규칙 전의 산출물일 수 있으므로 알리기만 한다.
                self.chapter("01").write_bytes(drafts["01"])
                code, output = self.check("plan")
                self.assertEqual(code, 0, output)
                self.assertIn(expected, output)
                self.chapter("01").unlink()
                path.write_text(original, encoding="utf-8")

    def test_scope_limit_without_an_owner_is_marked_out_of_scope(self):
        path = self.contract("01")
        path.write_text(path.read_text(encoding="utf-8").replace("→ **02장 소유**", "→ **범위 밖**"),
                        encoding="utf-8")
        code, output = self.check("plan")
        self.assertEqual(code, 0, output)
        self.assertNotIn("소유 챕터", output)

    def test_draft_warns_when_size_or_headings_miss_the_contract(self):
        self.write_chapter("01", text="# 장 01\n\n## 연습\n" + "가" * 400 + "\n\n## 다 읽고 나면\n정리")
        code, output = self.check("draft")
        self.assertEqual(code, 0, output)
        self.assertIn("01-chapter-01.md: 본문", output)
        self.assertIn("계약 분량 1~300자 밖", output)
        self.assertIn("`##` 소제목 1개 — 계약 질문 2개와 다르다", output)

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

    def test_bad_links_block_build(self):
        self.write_chapter("02", text="# 장\n[깨진 링크](missing.md)")
        self.reviews()
        self.assertEqual(self.run_book("build", str(self.root))[0], 1)

    def test_highlight_counter_ignores_inline_code(self):
        mark = '<mark style="background-color:#FFF3B0">결론</mark>'
        self.write_chapter("01", text=f"# 장 01\n## 연습\n{mark} `<mark>` `🟡🟢🔴` {mark} {mark}")
        self.reviews()
        code, output = self.check()
        self.assertEqual(code, 0, output)
        self.assertNotIn("형광펜", output)
        self.write_chapter("01", text=f"# 장 01\n## 연습\n{mark} {mark} {mark} 🟢 사례")
        self.reviews()
        self.assertIn("형광펜 4개", self.check()[1])


if __name__ == "__main__":
    unittest.main()
