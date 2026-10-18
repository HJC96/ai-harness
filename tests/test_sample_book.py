"""견본 교재로 단계별 게이트의 통과·실패 사례와 결함판의 격리를 검증한다."""
import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("claude_book", REPO / "shared/orchestration/book.py")
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)
SPEC = importlib.util.spec_from_file_location("baseline", REPO / "tests/fixtures/baseline.py")
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)
SPEC = importlib.util.spec_from_file_location("restamp", REPO / "tests/fixtures/restamp.py")
restamp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restamp)

FIXTURES = REPO / "tests/fixtures"
SAMPLE = FIXTURES / "견본"
ANSWERS = json.loads((FIXTURES / "정답/정답표.json").read_text(encoding="utf-8"))
STAGES = ("plan", "design", "draft", "review", "final")


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise AssertionError(f"{path.name}에 바꿀 문자열이 없다: {old}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# (이름, 처음 실패하는 stage, 기대 메시지, 견본 사본을 망가뜨리는 함수)
BREAKS = (
    ("목차 항목 미배정", "plan", "목차 3.2 항목",
     lambda r: edit(r / "00-설계/챕터계약/03.md", '"3.1", "3.2"', '"3.1"')),
    ("선수 순환", "plan", "의존성 순환",
     lambda r: edit(r / "00-설계/챕터계약/01.md", "선수챕터: []", '선수챕터: ["03"]')),
    ("계약 필드 누락", "plan", "`분량` 누락",
     lambda r: edit(r / "00-설계/챕터계약/02.md", "분량: 2000~3000자\n", "")),
    ("원고 누락", "draft", "03장: 원고가 없다",
     lambda r: (r / "chapters/03-bigdecimal-비교-나눗셈.md").unlink()),
    ("설계 검수 리포트 누락", "design", "설계 검수: 정확성·독자 리포트",
     lambda r: (r / "검수/설계-독자.md").unlink()),
    ("설계 검수 후 계약 수정", "design", "검수한 설계와 현재 00-설계가 다르다",
     lambda r: edit(r / "00-설계/챕터계약/02.md", "- 도식: 없음", "- 도식: 1개 (스케일 규칙)")),
    ("선수 요약 변경", "draft", "03장: 입력해시",
     lambda r: edit(r / "chapters/02-bigdecimal-표현.md", "아직 남았다.", "아직 남았고 반올림도 남았다.")),
    ("리포트 누락", "review", "03장: 정확성·독자 리포트",
     lambda r: (r / "검수/03-독자.md").unlink()),
    ("검수 후 원고 수정", "review", "02-정확성.md: 검수한 판본",
     lambda r: edit(r / "chapters/02-bigdecimal-표현.md", "이제 값은 정확하다.", "이제 값은 늘 정확하다.")),
    ("선수 본문 수정", "review", "02-독자.md: 검수입력해시",
     lambda r: edit(r / "chapters/01-double-오차.md", "코드는 단순하고", "코드는 짧고")),
    ("미해결 S1", "review", "미해결 S1",
     lambda r: edit(r / "검수/02-정확성.md", "S1: 0\n", "S1: 1\n")),
    ("index 누락", "final", "index.md가 필요하다",
     lambda r: (r / "index.md").unlink()),
    ("index의 장 링크 누락", "final", "03-bigdecimal-비교-나눗셈.md 링크 누락",
     lambda r: edit(r / "index.md", "](chapters/03-bigdecimal-비교-나눗셈.md)", "]")),
    ("확인 필요 표시 잔존", "final", "확인 필요 표시가 남아 있다",
     lambda r: edit(r / "index.md", "장마다 15분", "<!-- 확인 필요: 분량 --> 장마다 15분")),
)


class SampleBookTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="claude-sample-")
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name).resolve()
        self.root = self.temp / "book"
        shutil.copytree(SAMPLE, self.root)

    def run_book(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = book.main(list(args))
        return code, output.getvalue()

    def check(self, root, stage):
        return self.run_book("check", str(root), "--stage", stage)

    def test_sample_passes_every_stage_without_warnings_and_builds(self):
        for stage in STAGES:
            code, output = self.check(self.root, stage)
            self.assertEqual(code, 0, f"{stage}: {output}")
            self.assertNotIn("경고", output, f"{stage}: {output}")
        code, output = self.run_book("build", str(self.root))
        self.assertEqual(code, 0, output)
        combined = (self.root / "book.md").read_text(encoding="utf-8")
        for no in ("01", "02", "03"):
            self.assertIn(f'<a id="ch{no}"></a>', combined)

    def test_each_break_passes_earlier_stages_and_fails_from_its_stage(self):
        for name, stage, message, damage in BREAKS:
            with self.subTest(name):
                root = self.temp / name
                shutil.copytree(SAMPLE, root)
                damage(root)
                first = STAGES.index(stage)
                for earlier in STAGES[:first]:
                    code, output = self.check(root, earlier)
                    self.assertEqual(code, 0, f"{earlier}: {output}")
                for later in STAGES[first:]:
                    code, output = self.check(root, later)
                    self.assertEqual(code, 1, f"{later}: {output}")
                self.assertIn(message, self.check(root, stage)[1])

    def test_every_stage_has_a_failing_case(self):
        self.assertEqual({stage for _, stage, _, _ in BREAKS}, set(STAGES))

    def test_defect_editions_change_only_the_answer_lines(self):
        for edition, spec in ANSWERS["판"].items():
            with self.subTest(edition):
                expected = {}
                for defect in spec["결함"]:
                    expected.setdefault(defect["파일"], set()).update(defect["줄"])
                self.assertEqual(set(spec["덮어쓰기"]), set(expected))
                for target, source in spec["덮어쓰기"].items():
                    clean = (SAMPLE / target).read_text(encoding="utf-8").splitlines()
                    broken = (FIXTURES / source).read_text(encoding="utf-8").splitlines()
                    self.assertEqual(len(clean), len(broken))
                    changed = {i for i, pair in enumerate(zip(clean, broken), 1) if pair[0] != pair[1]}
                    self.assertEqual(changed, expected[target])

    def test_answered_check_marker_on_a_contract_owned_line_is_removed_not_left_to_block_final(self):
        # 9번 한 바퀴의 경우: 계약 귀속 S3가 남은 줄의 확인 필요 표시가 final을 막았다.
        chapter = self.root / "chapters/02-bigdecimal-표현.md"
        report = self.root / "검수/02-정확성.md"
        edit(chapter, "즉 17.991</mark>이 된다.", "즉 17.991</mark>이 된다. <!-- 확인 필요: 곱셈 스케일 -->")
        edit(chapter, "이미 double로 받은 값이라면", "<!-- 확인 필요: valueOf 경유 -->\n이미 double로 받은 값이라면")
        restamp.restamp(self.root)
        code, output = self.check(self.root, "review")
        self.assertEqual(code, 1, output)
        self.assertIn("02-bigdecimal-표현.md L22: 확인 필요 표시에 02-정확성.md가 답하지 않았다", output)
        self.assertIn("02-bigdecimal-표현.md L39: 확인 필요 표시에 02-정확성.md가 답하지 않았다", output)

        # 검수자가 한 표시는 계약 귀속 S3로, 다른 표시는 「근거 확인」으로 답한다(표시만 있는 줄은 다음 줄).
        edit(report, "S3: 0\n", "S3: 1\n")
        edit(report, "|---|---|---|---|---|---|\n\n지적 없음.",
             "|---|---|---|---|---|---|\n| S3-1 | S3 | 계약 | L22 | 계약이 스케일 표기를 정하지 않았다 | 계약에 표기를 둔다 |")
        edit(report, "## 근거 확인\n", "## 근거 확인\n- **L40** — `valueOf`가 `Double.toString`을 거친다: Javadoc\n")
        code, output = self.check(self.root, "review")
        self.assertEqual(code, 0, output)
        self.assertIn("L22: 확인 필요 표시 — 02-정확성.md가 답했다", output)
        self.assertIn("L39: 확인 필요 표시 — 02-정확성.md가 답했다", output)
        self.assertNotIn("02-정확성.md", self.run_book("check", str(self.root), "--stage", "review",
                                                       "--axis", "독자")[1])
        code, output = self.run_book("tally", str(self.root), "--chapter", "02")
        self.assertEqual(json.loads(output)["02"]["계약대기"], ["02/정확성/S3-1"])
        code, output = self.check(self.root, "final")
        self.assertEqual(code, 1)
        self.assertIn("L22: 확인 필요 표시가 남아 있다 — 02-정확성.md가 답했으니 편집자가 지운다", output)

        # 편집자가 주석만 지우면 표시는 사라지고, 바뀐 판본은 묶음 재검수로 간다.
        edit(chapter, " <!-- 확인 필요: 곱셈 스케일 -->", "")
        edit(chapter, "<!-- 확인 필요: valueOf 경유 -->\n", "")
        code, output = self.check(self.root, "final")
        self.assertNotIn("확인 필요", output)
        self.assertIn("02-정확성.md: 검수한 판본과 현재 원고가 다르다", output)

    def test_reviewer_copy_is_structurally_valid_and_carries_no_answers(self):
        hints = ("정답", "결함", "사실오류", "선수지식역전", "대조판")
        for i, (edition, spec) in enumerate(ANSWERS["판"].items()):
            with self.subTest(edition):
                copy = baseline.assemble(edition, self.temp / f"copy-{i}")
                design = spec.get("모드") == "설계"
                # 설계 판은 집필 전이라 원고가 없고, 설계 검수 리포트가 아직 없으므로 design부터 막힌다.
                code, output = self.check(copy, "plan" if design else "draft")
                self.assertEqual(code, 0, output)
                self.assertFalse((copy / "검수").exists())
                self.assertEqual((copy / "chapters").exists(), not design)
                for path in copy.rglob("*"):
                    if path.is_file():
                        text = path.read_text(encoding="utf-8")
                        for hint in hints + tuple(d["내용"] for d in spec["결함"]):
                            self.assertNotIn(hint, text, f"{path.relative_to(copy)}")
                            self.assertNotIn(hint, path.name)

    def test_clean_reports_score_zero_on_the_control_edition(self):
        copy = baseline.assemble("대조판", self.temp / "control")
        shutil.copytree(SAMPLE / "검수", copy / "검수")
        for report in sorted((copy / "검수").glob("*.md")):
            with self.subTest(report.name):
                result = baseline.score("대조판", report)
                self.assertTrue(result["해시 일치"])
                for key in ("적중", "누락", "오탐", "S3"):
                    self.assertEqual(result[key], [], key)

    def test_score_counts_hits_near_the_answer_line_and_other_rows_as_false_alarms(self):
        copy = baseline.assemble("사실오류", self.temp / "scored")
        shutil.copytree(SAMPLE / "검수", copy / "검수")
        report = copy / "검수/02-정확성.md"
        edit(report, "|---|---|---|---|---|---|\n",
             "|---|---|---|---|---|---|\n"
             "| S2-1 | S2 | 원고 | L38-L40 | valueOf 설명이 틀렸다 | 고친다 |\n"
             "| S2-2 | S2 | 원고 | L12 | 단정 | 낮춘다 |\n"
             "| S2-3 | S2 | 원고 | 2.1절 | 위치 없는 지적 | 적는다 |\n"
             "| S3-1 | S3 | L5 | 귀속 열이 없는 이전 형식 | 다듬는다 |\n")
        result = baseline.score("사실오류", report)
        self.assertFalse(result["해시 일치"])
        self.assertEqual(result["적중"], ["사실-1"])
        self.assertEqual(result["심각도 일치"], [])
        self.assertEqual(result["누락"], [])
        self.assertEqual(result["오탐"], ["S2-2", "S2-3"])
        self.assertEqual(result["위치 없음"], ["S2-3"])
        self.assertEqual(result["S3"], ["S3-1"])
        # 다른 축 리포트에는 이 판의 정답이 없다.
        self.assertEqual(baseline.score("사실오류", copy / "검수/02-독자.md")["누락"], [])

    def test_design_score_needs_the_file_name_as_well_as_the_line(self):
        copy = baseline.assemble("설계선수지식역전", self.temp / "design")
        (copy / "검수").mkdir()
        shutil.copyfile(SAMPLE / "검수/설계-독자.md", copy / "검수/설계-독자.md")
        report = copy / "검수/설계-독자.md"
        edit(report, "|---|---|---|---|---|---|\n",
             "|---|---|---|---|---|---|\n"
             "| S1-1 | S1 | 계약 | 03.md L30 | 다른 계약의 같은 줄 | 옮긴다 |\n"
             "| S2-1 | S2 | 계약 | L30 | 파일 없는 위치 | 적는다 |\n"
             "| S1-2 | S1 | 계약 | 01.md L5, 02.md L26, L31 | 반올림을 전제한다 | 옮긴다 |\n")
        result = baseline.score("설계선수지식역전", report)
        self.assertIs(result["해시 일치"], False)
        self.assertEqual(result["챕터"], "설계")
        self.assertEqual(result["적중"], ["설계역전-1"])
        self.assertEqual(result["심각도 일치"], ["설계역전-1"])
        self.assertEqual(result["오탐"], ["S1-1", "S2-1"])
        self.assertEqual(result["위치 없음"], ["S2-1"])
        # 원본 설계에서 받은 정상 리포트는 사본의 설계와 해시가 같다.
        control = baseline.assemble("설계대조판", self.temp / "design-control")
        shutil.copytree(SAMPLE / "검수", control / "검수")
        for axis in ("정확성", "독자"):
            result = baseline.score("설계대조판", control / f"검수/설계-{axis}.md")
            self.assertTrue(result["해시 일치"])
            self.assertEqual((result["적중"], result["누락"], result["오탐"]), ([], [], []))


if __name__ == "__main__":
    unittest.main()
