#!/usr/bin/env python3
"""견본 교재의 해시 필드를 다시 계산한다. 견본 전용이다.

  python3 tests/fixtures/restamp.py

견본 원고·계약·설계를 고치거나 book.py의 해시 정의가 바뀐 뒤에만 쓴다.
실제 책에서 판정 없이 해시만 갱신하는 것은 파이프라인 규칙 위반이므로
경로 인자를 받지 않고 tests/fixtures/견본만 고친다. 테스트는 견본 사본에 `restamp(사본)`을 쓴다.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "견본"
SPEC = importlib.util.spec_from_file_location("claude_book", HERE.parents[1] / "shared/orchestration/book.py")
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)


def stamp(path, values):
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text, count = re.subn(rf"^{key}: .*$", f"{key}: {value}", text, count=1, flags=re.M)
        if count != 1:
            raise SystemExit(f"{path.name}: `{key}` 줄이 없다")
    path.write_text(text, encoding="utf-8")


def restamp(root):
    contracts, chapters, _ = book.load_book(root)
    # 입력해시는 선수 요약만 보므로 원고끼리의 순서와 무관하다.
    for no, (path, _) in chapters.items():
        stamp(path, {"입력해시": book.input_hash(root, no, contracts, chapters)})
    # 독자 축 검수입력해시는 선수 원고 전체를 보므로 원고를 모두 고친 뒤에 계산한다.
    contracts, chapters, reviews = book.load_book(root)
    for no, reports in reviews.items():
        for path, meta in reports:
            if no == book.DESIGN:
                target = book.tree_hash(root / book.DESIGN_DIR)
                stamp(path, {"대상해시": target})
            else:
                target = book.sha256(chapters[no][0])
                stamp(path, {"대상해시": target,
                             "계약해시": book.sha256(contracts[no][0]),
                             "검수입력해시": book.review_input_hash(root, no, contracts, chapters, meta["축"])})
            # 견본 리포트의 이력은 1회차 한 행뿐이다. 그 행이 frontmatter와 같은 판본을 가리키게 한다.
            text, count = re.subn(r"^(\| 1 \| 첫 검수 \| )[0-9a-f]{64}( \|)", rf"\g<1>{target}\g<2>",
                                  path.read_text(encoding="utf-8"), flags=re.M)
            if count != 1:
                raise SystemExit(f"{path.name}: 검수 이력 1회차 행이 없다")
            path.write_text(text, encoding="utf-8")
    if book.ERR:
        raise SystemExit("\n".join(book.ERR))


def main():
    restamp(SAMPLE)
    return book.main(["check", str(SAMPLE)])


if __name__ == "__main__":
    sys.exit(main())
