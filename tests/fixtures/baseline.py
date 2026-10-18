#!/usr/bin/env python3
"""검수자 측정용 사본을 조립하고, 받은 리포트를 정답표로 채점한다.

  python3 tests/fixtures/baseline.py assemble <판> <사본경로>
  python3 tests/fixtures/baseline.py score <판> <리포트>...

사본에는 정답표·결함판·판 이름이 들어가지 않는다. 사본 경로에도 판 이름을 넣지 않는다.
`모드: 설계`인 판의 사본에는 원고·index.md도 없다 — 설계 검수는 집필 전에 돈다.
채점은 리포트의 `축`과 `대상`(챕터, 또는 설계 리포트면 `설계`)에 해당하는 심어 둔 결함만 정답으로 본다.
리포트는 사본의 `검수/` 아래에 있어야 대상 원고·설계의 해시를 대조할 수 있다.
"""
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "견본"
ANSWERS = json.loads((HERE / "정답/정답표.json").read_text(encoding="utf-8"))
SPEC = importlib.util.spec_from_file_location("claude_book", HERE.parents[1] / "shared/orchestration/book.py")
book = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(book)

# 위치 줄 번호가 정답 줄에서 이만큼 벗어나도 같은 자리로 본다. 문단 범위로 적는 경우를 받기 위해서다.
SLACK = 1
# 귀속 열(`원고`·`계약`)이 없는 3b 이전 리포트도 읽는다.
ROW = re.compile(r"^\|\s*(S[123]-\d+)\s*\|\s*(S[123]|해결)\s*\|(?:\s*(?:원고|계약)\s*\|)?([^|]*)\|")
LINES = re.compile(r"(?:([^\s,|]+\.md)\s+)?L(\d+)(?:\s*[-–~]\s*L?(\d+))?")


def assemble(edition, dest):
    """견본을 복사하고 리포트를 뺀 뒤 그 판의 결함판 파일을 덮어쓴다. 설계 판은 원고도 뺀다."""
    dest = Path(dest)
    shutil.copytree(SAMPLE, dest)
    shutil.rmtree(dest / "검수")
    if ANSWERS["판"][edition].get("모드") == "설계":
        shutil.rmtree(dest / "chapters")
        (dest / "index.md").unlink()
    for target, source in ANSWERS["판"][edition]["덮어쓰기"].items():
        shutil.copyfile(HERE / source, dest / target)
    return dest


def cited_lines(cell):
    """위치 칸의 `L<n>`·`L<n>-<m>`을 (파일 이름, 줄 번호) 집합으로. 없으면 빈 집합.

    설계 리포트의 `02.md L21, L30`처럼 파일 이름이 빠진 뒤 위치는 앞의 파일을 잇는다. 챕터 리포트는 파일이 None이다."""
    lines, current = set(), None
    for name, start, end in LINES.findall(cell):
        current = Path(name).name if name else current
        lines.update((current, n) for n in range(int(start), int(end or start) + 1))
    return lines


def rows(report):
    """미해결 지적 행 (ID, 심각도, (파일, 줄 번호) 집합)."""
    for line in book.body(report).splitlines():
        m = ROW.match(line)
        if m and m.group(2) != "해결":
            yield m.group(1), m.group(2), cited_lines(m.group(3))


def score(edition, report):
    report = Path(report).resolve()
    meta = book.frontmatter(report)
    target = report.parent.parent / meta["대상"]
    design = meta["대상"] == book.DESIGN_DIR
    chapter = book.DESIGN if design else Path(meta["대상"]).name[:2]
    defects = [d for d in ANSWERS["판"][edition]["결함"] if d["축"] == meta["축"] and d["챕터"] == chapter]
    found, extra, s3, unplaced = {}, [], [], []
    # 챕터 리포트는 대상이 한 파일이라 줄만, 설계 리포트는 파일 이름까지 맞아야 같은 자리다.
    spot = lambda d: {(Path(d["파일"]).name if design else None, n) for n in d["줄"]}
    for rid, severity, lines in rows(report):
        lines = {(f, n) for f, n in lines if f} if design else {(None, n) for _, n in lines}
        near = {(f, n + d) for f, n in lines for d in range(-SLACK, SLACK + 1)}
        match = next((d for d in defects if d["ID"] not in found and near & spot(d)), None)
        if match:
            found[match["ID"]] = severity
        elif severity == "S3":
            s3.append(rid)
        else:
            extra.append(rid)
            if not lines:
                unplaced.append(rid)
    return {
        "리포트": str(report),
        "축": meta["축"],
        "챕터": chapter,
        "해시 일치": meta.get("대상해시") == (book.tree_hash(target) if design else
                                         book.sha256(target) if target.is_file() else None),
        "적중": sorted(found),
        "심각도 일치": sorted(i for i, s in found.items() if s == next(d["심각도"] for d in defects if d["ID"] == i)),
        "누락": sorted(d["ID"] for d in defects if d["ID"] not in found),
        "오탐": extra,
        "위치 없음": unplaced,
        "S3": s3,
    }


def main(argv):
    if len(argv) >= 3 and argv[0] == "assemble":
        print(assemble(argv[1], argv[2]))
        return 0
    if len(argv) >= 3 and argv[0] == "score":
        for report in argv[2:]:
            print(json.dumps(score(argv[1], report), ensure_ascii=False))
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
