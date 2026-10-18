#!/usr/bin/env python3
"""교재 산출물 점검·합본 도구.

  python3 shared/orchestration/book.py check <출력경로> --stage intake|plan|design|draft|review|final [--axis 정확성|독자]
  python3 shared/orchestration/book.py build <출력경로> [합본경로]
  python3 shared/orchestration/book.py hash <파일 또는 디렉터리>
  python3 shared/orchestration/book.py inputs <출력경로> <챕터번호>
  python3 shared/orchestration/book.py review-inputs <출력경로> <챕터번호> 정확성|독자
  python3 shared/orchestration/book.py tally <출력경로> [--chapter NN]

판단은 하지 않는다. 기계로 확인할 수 있는 것만 본다 —
접수한 목차와 상태 파일, 설계 점검표 중 셀 수 있는 것, 설계 검수, 계약 버전 일치,
검수 판정의 신선도, 검수 이력·귀속과 상한, 확인 필요 표시의 답, 미확인 수락, 링크·앵커,
목차 항목 누락, 분량·소제목 수, 형광펜 개수.
"""
import argparse
import ast
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

if sys.version_info < (3, 9):
    raise SystemExit("Python 3.9 이상이 필요하다.")

ERR, WARN = [], []
def err(m): ERR.append(m)
def warn(m): WARN.append(m)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(path: Path) -> str:
    """디렉터리 아래 모든 파일의 상대 경로와 내용을 묶은 지문. `.`으로 시작하는 이름은 뺀다."""
    files = {f.relative_to(path).as_posix(): sha256(f) for f in sorted(path.rglob("*"))
             if f.is_file() and not any(part.startswith(".") for part in f.relative_to(path).parts)}
    return hashlib.sha256(json.dumps(files, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def frontmatter(path: Path, text=None) -> dict:
    """문서 계약의 YAML 부분집합. 지원하지 않는 문법은 조용히 무시하지 않는다."""
    text = path.read_text(encoding="utf-8") if text is None else text
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not match:
        raise ValueError(f"{path.name}: frontmatter가 없거나 닫히지 않았다")
    data, key = {}, None
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.lstrip().startswith("- ") and key:
            if not isinstance(data[key], list):
                raise ValueError(f"{path.name}: {key}는 목록이 아니다")
            data[key].append(scalar(line.lstrip()[2:].strip()))
            continue
        if line[0].isspace() or ":" not in line:
            raise ValueError(f"{path.name}: 지원하지 않는 frontmatter 문법: {line}")
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not key or key in data:
            raise ValueError(f"{path.name}: 비어 있거나 중복된 키: {key}")
        if value.startswith("["):
            try:
                items = ast.literal_eval(value)
            except (ValueError, SyntaxError) as exc:
                raise ValueError(f"{path.name}: {key}는 따옴표로 감싼 문자열 목록이어야 한다") from exc
            if not isinstance(items, list) or any(not isinstance(v, str) for v in items):
                raise ValueError(f"{path.name}: {key}는 문자열 목록이어야 한다")
            data[key] = items
        else:
            data[key] = scalar(value) if value else []
    return data


def scalar(value):
    if value.startswith(('"', "'")):
        try:
            result = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"잘못된 인용 문자열: {value}") from exc
        if not isinstance(result, str):
            raise ValueError("스칼라는 문자열이어야 한다")
        return result
    value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
    if value in ("|", ">", "|-", ">-") or value.startswith(("{", "&", "*")):
        raise ValueError("중첩 객체·여러 줄 값·YAML 앵커는 지원하지 않는다")
    return value


def body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return re.sub(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", "", text, count=1, flags=re.S)


def unfenced(text: str):
    """코드 펜스 밖의 줄만 (번호, 내용)으로 내놓는다."""
    marker = None
    for i, line in enumerate(text.splitlines(), 1):
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            token, rest = fence.groups()
            if marker is None:
                marker = token
            elif token[0] == marker[0] and len(token) >= len(marker) and not rest.strip():
                marker = None
            continue
        if marker is None:
            yield i, line


def slug(heading: str) -> str:
    s = re.sub(r"\s+#+\s*$", "", heading.strip()).lower()
    s = re.sub(r"<[^>]*>", "", s)
    s = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", s)
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", s))


def heading_ids(path):
    used, result = set(), {}
    for ln, line in unfenced(body(path)):
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if m:
            base = slug(m.group(1))
            candidate, i = base, 0
            while candidate in used:
                i += 1
                candidate = f"{base}-{i}"
            used.add(candidate)
            result[ln] = candidate
    return result


def anchors(path: Path) -> set:
    out = set(heading_ids(path).values())
    for _, line in unfenced(body(path)):
        for a in re.findall(r'<a\s+(?:id|name)=["\']([^"\']+)', line):
            out.add(a)
    return out


# 계약은 인라인 Markdown 링크만 사용한다. 코드 안의 예제 링크는 검사하지 않는다.
LINK = re.compile(r'\]\((<[^>\n]+>|[^\s()]+)(?:\s+"[^"\n]*")?\)')


def prose_parts(line):
    return re.split(r"(`+[^`]*`+)", line)


def local_target(source, target):
    parsed = urlsplit(target.strip("<>"))
    if parsed.scheme or parsed.netloc:
        return None
    return ((source.parent / unquote(parsed.path)).resolve() if parsed.path else source.resolve(),
            unquote(parsed.fragment))


# ---------------------------------------------------------------- check

DESIGN = "설계"
DESIGN_DIR = "00-설계"


def load_book(root: Path):
    """계약·원고·검수 리포트. 설계 검수 리포트는 reviews의 `설계` 키에 둔다."""
    contracts, chapters, reviews = {}, {}, {}
    for directory, target in ((root / "00-설계/챕터계약", contracts),
                              (root / "chapters", chapters), (root / "검수", reviews)):
        for p in sorted(directory.glob("*.md")):
            try:
                fm = frontmatter(p)
                no = p.stem.split("-")[0] if target is reviews else fm.get("번호", "")
                if target is reviews and no == DESIGN:
                    target.setdefault(no, []).append((p, fm))
                    continue
                if not isinstance(no, str) or not re.fullmatch(r"[0-9]{2,}", no):
                    raise ValueError(f"{p.name}: 번호는 01처럼 2자리 이상의 숫자 문자열이어야 한다")
                if target is reviews:
                    target.setdefault(no, []).append((p, fm))
                elif no in target:
                    raise ValueError(f"{no}장: 번호가 중복됐다 ({p.name})")
                else:
                    target[no] = (p, fm)
            except (OSError, ValueError) as exc:
                err(str(exc))
    return contracts, chapters, reviews


def input_hash(root, no, contracts, chapters):
    """집필자가 실제로 읽은 계약·설계·선수 요약의 지문. 파일은 수정하지 않는다."""
    cp, fm = contracts[no]
    predecessors = fm.get("선수챕터")
    if not isinstance(predecessors, list):
        raise ValueError(f"{no}장: 선수챕터 목록이 없다")
    snapshot = {"계약": sha256(cp), "설계": sha256(root / "00-설계/설계서.md"),
                "선수요약": {}}
    for dep in predecessors:
        if dep not in chapters:
            raise ValueError(f"{no}장: 선수 {dep}장 원고가 없다")
        snapshot["선수요약"][dep] = chapters[dep][1].get("요약", "")
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


AXES = ("정확성", "독자")
# 검수입력해시의 판본. 접두가 없는 값은 축을 나누기 전의 v1이다.
REVIEW_INPUTS = "v2"


def review_input_hash(root, no, contracts, chapters, axis):
    """축의 검수자가 판정 근거로 읽는 파일의 지문. 정확성은 설계·계약, 독자는 설계·선수 본문."""
    if axis not in AXES:
        raise ValueError(f"{no}장: 알 수 없는 검수 축 {axis}")
    snapshot = {"축": axis, "설계": sha256(root / "00-설계/설계서.md")}
    if axis == "정확성":
        snapshot["계약"] = sha256(contracts[no][0])
    else:
        deps = contracts[no][1].get("선수챕터")
        if not isinstance(deps, list):
            raise ValueError(f"{no}장: 선수챕터 목록이 없다")
        snapshot["선수본문"] = {}
        for dep in deps:
            if dep not in chapters:
                raise ValueError(f"{no}장: 선수 {dep}장 원고가 없다")
            snapshot["선수본문"][dep] = sha256(chapters[dep][0])
    digest = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return f"{REVIEW_INPUTS}:{digest}"


def positive(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value)


# ---------------------------------------------------------------- 검수 리포트

TRIGGERS = ("첫 검수", "재집필", "편집", "입력 변경")
HISTORY = ["회차", "계기", "대상해시", "계약버전", "판정", "미해결 S1"]
# 설계 검수 리포트의 이력에는 계약버전이 없다. 판정은 00-설계 디렉터리 해시에 묶인다.
DESIGN_TRIGGERS = ("첫 검수", "재설계")
DESIGN_HISTORY = ["회차", "계기", "대상해시", "판정", "미해결 S1"]
OWNERS = ("원고", "계약")
# 값과 이유는 교재-파이프라인.md 「막혔을 때」. 계약버전마다 새로 센다.
SURVIVAL_LIMIT, REWRITE_LIMIT = 2, 4
ACCEPTED = "미확인-수락.md"


def verdict(counts):
    return "재집필 필요" if counts["S1"] else "수정 권고" if counts["S2"] else "통과"


def section(text, title):
    """`## 제목` 아래부터 다음 `## ` 제목 전까지, 코드 펜스 밖의 줄."""
    out, inside = [], False
    for _, line in unfenced(text):
        if re.match(r"^##\s", line):
            inside = line[2:].strip() == title
        elif inside:
            out.append(line)
    return out


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_report(rp, rfm, design=False):
    """지적·귀속·미확인·검수 이력을 읽고 리포트 안의 일관성을 확인한다. 판본 신선도는 check가 본다.

    findings는 지적 ID → (심각도, 귀속). design이면 설계 검수 리포트의 규격으로 읽는다."""
    text = body(rp)
    counts, findings, unknowns = {"S1": 0, "S2": 0, "S3": 0}, {}, []
    owners = ("계약",) if design else OWNERS
    for _, line in unfenced(text):
        m = re.match(r"^\|\s*(S[123]-\d+)\s*\|\s*(S[123]|해결)\s*\|\s*([^|]*?)\s*\|", line)
        if re.match(r"^\|\s*S[123]-", line) and not m:
            err(f"{rp.name}: 잘못된 지적 ID 또는 심각도 행")
        if m:
            identity, severity, owner = m.groups()
            if identity in findings:
                err(f"{rp.name}: 지적 ID 중복 {identity}")
            if owner not in owners:
                err(f"{rp.name}: {identity}의 귀속은 {' 또는 '.join(owners)}이다 (지금 `{owner}`)")
            findings[identity] = (severity, owner)
            if severity in counts:
                counts[severity] += 1
        u = re.match(r"^\|\s*(U-[1-9][0-9]*)\s*\|", line)
        if re.match(r"^\|\s*U-", line) and not u:
            err(f"{rp.name}: 잘못된 미확인 ID 행")
        if u:
            if u.group(1) in unknowns:
                err(f"{rp.name}: 미확인 ID 중복 {u.group(1)}")
            unknowns.append(u.group(1))
    for key, count in (*counts.items(), ("미확인", len(unknowns))):
        value = rfm.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
            err(f"{rp.name}: `{key}`는 0 이상의 정수여야 한다")
        elif int(value) != count:
            err(f"{rp.name}: `{key}` 개수와 표가 다르다")

    expected = verdict(counts)
    stated = [line.strip() for line in section(text, "판정") if line.strip()]
    if not stated or stated[0] != expected:
        err(f"{rp.name}: 「판정」이 미해결 개수에서 나온 `{expected}`와 다르다")

    columns, triggers = (DESIGN_HISTORY, DESIGN_TRIGGERS) if design else (HISTORY, TRIGGERS)
    rows = [cells(line) for line in section(text, "검수 이력") if line.lstrip().startswith("|")]
    if len(rows) < 3 or rows[0] != columns or not all(re.fullmatch(r":?-+:?", c) for c in rows[1]):
        err(f"{rp.name}: 「검수 이력」 표가 없거나 열이 `{' | '.join(columns)}`가 아니다")
        return counts, findings, unknowns, None
    history, version = [], 0
    for i, row in enumerate(rows[2:], 1):
        where = f"{rp.name}: 검수 이력 {i}행"
        if len(row) != len(columns):
            err(f"{where}의 칸 수가 다르다")
            return counts, findings, unknowns, None
        record = dict(zip(columns, row))
        record.setdefault("계약버전", None)
        open_ids = [] if record["미해결 S1"] == "없음" else [s.strip() for s in record["미해결 S1"].split(",")]
        if record["회차"] != str(i):
            err(f"{where}: 회차는 1부터 1씩 늘어야 한다")
        if record["계기"] not in triggers:
            err(f"{where}: 계기는 {' · '.join(triggers)} 중 하나다")
        if not re.fullmatch(r"[0-9a-f]{64}", record["대상해시"]):
            err(f"{where}: 대상해시는 64자리 해시 전체 값이어야 한다")
        if not design:
            if not positive(record["계약버전"]) or int(record["계약버전"]) < version:
                err(f"{where}: 계약버전이 양의 정수가 아니거나 줄었다")
            else:
                version = int(record["계약버전"])
        if record["판정"] not in ("재집필 필요", "수정 권고", "통과"):
            err(f"{where}: 판정이 잘못됐다")
        if not all(re.fullmatch(r"S[123]-[1-9][0-9]*", s) for s in open_ids):
            err(f"{where}: 미해결 S1은 `없음` 또는 쉼표로 나눈 지적 ID다")
        record["미해결 S1"] = set(open_ids)
        history.append(record)
    last = history[-1]
    if last["대상해시"] != rfm.get("대상해시") or (not design and last["계약버전"] != rfm.get("계약버전")):
        err(f"{rp.name}: 검수 이력 마지막 행의 대상해시{'' if design else '·계약버전'}이 frontmatter와 다르다")
    if last["판정"] != expected:
        err(f"{rp.name}: 검수 이력 마지막 행의 판정이 `{expected}`가 아니다")
    if last["미해결 S1"] != {i for i, (s, _) in findings.items() if s == "S1"}:
        err(f"{rp.name}: 검수 이력 마지막 행의 미해결 S1이 지적 표와 다르다")
    return counts, findings, unknowns, history


def survivals(rows, rework):
    """처음 미해결 S1로 나온 뒤, rework 회차(바로 앞 행과 대상해시가 다른)에서 다시 미해결 S1로 나온 횟수."""
    survived, seen = {}, set()
    for i, row in enumerate(rows):
        if row["계기"] == rework and (i == 0 or rows[i - 1]["대상해시"] != row["대상해시"]):
            for identity in row["미해결 S1"] & seen:
                survived[identity] = survived.get(identity, 0) + 1
        seen |= row["미해결 S1"]
    return survived


def tally_chapter(no, histories, current, findings=None):
    """한 챕터의 두 축 이력에서 상한을 센다(산출물 계약 3절 「상한 집계」).

    findings는 축 → {지적 ID: (심각도, 귀속)}. 귀속이 계약인 열린 S1은 `계약귀속`,
    열린 S2·S3는 다음 계약 수정에 동봉할 `계약대기`로 따로 낸다."""
    rewrites, edits, opened, contract, waiting, blocked = set(), set(), {}, [], [], []
    for axis, full in sorted(histories.items()):
        rows = [row for row in full if row["계약버전"] == current]
        rewrites.update(row["대상해시"] for row in rows if row["계기"] == "재집필")
        edits.update(row["대상해시"] for row in rows if row["계기"] == "편집")
        survived = survivals(rows, "재집필")
        if not full or full[-1]["계약버전"] != current:
            continue
        own = (findings or {}).get(axis, {})
        for identity in sorted(full[-1]["미해결 S1"]):
            opened[f"{no}/{axis}/{identity}"] = survived.get(identity, 0)
            if own.get(identity, (None, None))[1] == "계약":
                contract.append(f"{no}/{axis}/{identity}")
        waiting += [f"{no}/{axis}/{identity}" for identity, (severity, owner) in sorted(own.items())
                    if severity in ("S2", "S3") and owner == "계약"]
    for key, count in opened.items():
        if count >= SURVIVAL_LIMIT:
            blocked.append(f"같은 지적 {key}이 재집필 {count}회를 살아남았다")
    if opened and len(rewrites) >= REWRITE_LIMIT:
        blocked.append(f"재집필 {len(rewrites)}회에도 미해결 S1이 남았다 — 계약 문제로 본다")
    return {"계약버전": current, "재집필": len(rewrites), "편집": len(edits),
            "열린지적": opened, "계약귀속": contract, "계약대기": waiting, "막힘": blocked}


def tally_design(histories):
    """설계 검수 리포트의 상한. 계약버전으로 나누지 않고 같은 지적의 재설계 생존만 센다."""
    redesigns, opened, blocked = set(), {}, []
    for axis, rows in sorted(histories.items()):
        redesigns.update(row["대상해시"] for row in rows if row["계기"] == "재설계")
        survived = survivals(rows, "재설계")
        for identity in sorted(rows[-1]["미해결 S1"]):
            opened[f"{DESIGN}/{axis}/{identity}"] = survived.get(identity, 0)
    for key, count in opened.items():
        if count >= SURVIVAL_LIMIT:
            blocked.append(f"같은 설계 지적 {key}이 재설계 {count}회를 살아남았다")
    return {"재설계": len(redesigns), "열린지적": opened, "막힘": blocked}


def accepted(root):
    """사용자가 수락한 (추적 키, 대상해시). 지휘자가 추가만 하는 기록이다."""
    path, out = root / ACCEPTED, set()
    if not path.is_file():
        return out
    for ln, line in unfenced(path.read_text(encoding="utf-8")):
        if not re.match(r"^\|\s*[0-9]", line):
            continue
        m = re.match(r"^\|\s*([0-9]{2,}/(?:정확성|독자)/U-[1-9][0-9]*)\s*\|\s*([0-9a-f]{64})\s*\|", line)
        if m:
            out.add(m.groups())
        else:
            err(f"{ACCEPTED}:{ln}: 추적 키 또는 대상해시 형식이 잘못됐다")
    return out


def tally(root: Path, selected=None):
    contracts, chapters, reviews = load_book(root)
    result = {}
    for no in sorted(set(selected or contracts)):
        if no not in contracts:
            err(f"{no}장: 계약이 없다")
            continue
        histories, owned = {}, {}
        for rp, rfm in reviews.get(no, []):
            _, findings, _, history = parse_report(rp, rfm)
            if history is not None:
                histories[rfm.get("축")] = history
                owned[rfm.get("축")] = findings
        result[no] = tally_chapter(no, histories, contracts[no][1].get("계약버전"), owned)
    if not selected and reviews.get(DESIGN):
        histories = {}
        for rp, rfm in reviews[DESIGN]:
            history = parse_report(rp, rfm, design=True)[3]
            if history is not None:
                histories[rfm.get("축")] = history
        result[DESIGN] = tally_design(histories)
    return result


# ---------------------------------------------------------------- 접수 · 설계 점검표

STAGES = ("intake", "plan", "design", "draft", "review", "final")
STATE = ".교재상태.json"
STATE_KEYS = ("책", "출력경로", "목차원본", "독자", "깊이", "phase", "챕터", "갱신")
DEPTHS = ("표준", "압축", "정밀")
QUESTIONS = "다 읽으면 답할 수 있는 질문"
CONTRACT_SECTIONS = ("한 줄 목표", QUESTIONS, "다루는 것", "다루지 않는 것", "관통 사례에서 쓰는 장면",
                     "필수 포함", "이어받을 문장", "넘길 것", "이 챕터에서 처음 정의하는 용어",
                     "근거 확인 필요 항목")
DESIGN_SECTIONS = ("학습 경로", "의존성 그래프", "관통 사례", "용어집", "원래 목차에서 바꾼 것", "챕터 목록")
WRAP_UP = "다 읽고 나면"


def toc_items(root):
    """번호를 붙인 목차.md의 항목 번호. 번호가 겹치면 어느 항목이 배정된 것인지 알 수 없다."""
    toc = root / "목차.md"
    if not toc.is_file():
        err("목차.md가 없다. 번호를 붙인 원문 목차가 필요하다")
        return None
    items = set()
    for _, line in unfenced(toc.read_text(encoding="utf-8")):
        m = re.match(r"^\s*(?:#{1,6}\s+|[-*]\s+)?(\d+(?:\.\d+)*)(?:[.)]?\s+)", line)
        if m:
            if m.group(1) in items:
                err(f"목차.md: 항목 번호 {m.group(1)}이 겹친다")
            items.add(m.group(1))
    if not items:
        err("목차.md에 검사 가능한 번호 항목이 없다")
    return items


def intake(root):
    """Phase 0 접수 게이트. 계약이 없어도 돈다(산출물 계약 5절)."""
    original = root / "목차-원문.md"
    if not original.is_file() or not original.read_text(encoding="utf-8").strip():
        err("목차-원문.md가 없거나 비었다. 사용자 입력 원문을 보존한다")
    toc_items(root)
    try:
        state = json.loads((root / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        err(f"{STATE} 파일이 없거나 JSON이 아니다: {exc.__class__.__name__}")
        return
    if not isinstance(state, dict):
        err(f"{STATE}: 최상위가 객체가 아니다")
        return
    for key in STATE_KEYS:
        if key not in state:
            err(f"{STATE}: `{key}` 누락")
    for key in ("책", "출력경로", "독자", "갱신"):
        if key in state and (not isinstance(state[key], str) or not state[key].strip()):
            err(f"{STATE}: `{key}`가 비었다")
    if "깊이" in state and state["깊이"] not in DEPTHS:
        err(f"{STATE}: `깊이`는 {' · '.join(DEPTHS)} 중 하나다")
    phase = state.get("phase")
    if "phase" in state and (type(phase) is not int or not 0 <= phase <= 5):
        err(f"{STATE}: `phase`는 0~5의 정수다")
    if "챕터" in state and not isinstance(state["챕터"], list):
        err(f"{STATE}: `챕터`는 목록이다")
    source = state.get("목차원본")
    if "목차원본" in state and (not isinstance(source, str) or not source.strip()
                               or not (root / source).is_file()):
        err(f"{STATE}: `목차원본`이 출력 경로 기준으로 있는 파일이 아니다")


def size_range(value):
    """계약 `분량`(`4000~5500자`, `3000자`)을 (하한, 상한)으로. 형식이 틀리면 None."""
    m = re.fullmatch(r"([0-9][0-9,]*)(?:\s*~\s*([0-9][0-9,]*))?\s*자", value.strip()) if isinstance(value, str) else None
    if not m:
        return None
    low, high = (int(v.replace(",", "")) for v in (m.group(1), m.group(2) or m.group(1)))
    return (low, high) if low <= high else None


def filled(text, title):
    return [line.strip() for line in section(text, title) if line.strip()]


def questions(text):
    return [line for line in filled(text, QUESTIONS) if re.match(r"^[0-9]+\.\s+\S", line)]


def table(text, title, head):
    """절 안에서 머리 칸이 head로 시작하는 첫 표의 데이터 행. 없으면 None."""
    block = []
    for line in section(text, title) + [""]:
        if line.lstrip().startswith("|"):
            block.append(cells(line))
            continue
        if (len(block) >= 2 and block[0][:len(head)] == list(head)
                and all(re.fullmatch(r":?-+:?", c) for c in block[1])):
            return block[2:]
        block = []
    return None


def levels(graph):
    """선수 없으면 0, 아니면 선수 레벨의 최댓값 + 1. 순환에 걸린 챕터는 빠진다."""
    out = {}
    def level(no, path=()):
        if no in out or no in path:
            return out.get(no)
        deps = [level(dep, path + (no,)) for dep in graph[no] if dep in graph]
        if None not in deps:
            out[no] = max(deps, default=-1) + 1
        return out.get(no)
    for no in graph:
        level(no)
    return out


def check_design(root, contracts, graph, report):
    """설계 점검표 중 셀 수 있는 것(산출물 계약 1·4절). report는 err 또는 warn이다."""
    for no, (p, fm) in sorted(contracts.items()):
        text = body(p)
        for title in CONTRACT_SECTIONS:
            if not filled(text, title):
                report(f"{p.name}: 「{title}」 절이 없거나 비었다")
        count = len(questions(text))
        if not 2 <= count <= 3:
            report(f"{p.name}: 질문은 번호를 붙인 줄로 2~3개다 (지금 {count}개)")
        for line in filled(text, "다루지 않는 것"):
            if line.lstrip("-* ").strip() == "없음":
                continue
            m = re.search(r"\*\*(?:(?:([0-9]{2,})장|부록 \S+) 소유|범위 밖)\*\*", line)
            if not m:
                report(f"{p.name}: 「다루지 않는 것」에 소유 챕터 번호가 없다(`범위 밖`도 아니다): {line}")
            elif m.group(1) and (m.group(1) == no or m.group(1) not in contracts):
                report(f"{p.name}: 「다루지 않는 것」의 소유 챕터 {m.group(1)}장이 자기 자신이거나 계약이 없다")
        if isinstance(fm.get("분량"), str) and fm["분량"].strip() and not size_range(fm["분량"]):
            report(f"{p.name}: `분량`은 `4000~5500자` 또는 `3000자` 꼴이다")

    design = root / "00-설계/설계서.md"
    if not design.is_file():
        return
    text = body(design)
    for title in DESIGN_SECTIONS:
        if not filled(text, title):
            report(f"설계서: 「{title}」 절이 없거나 비었다")
    rows = table(text, "의존성 그래프", ("레벨", "챕터"))
    if rows is None:
        report("설계서: 「의존성 그래프」에 `레벨 | 챕터` 표가 없다")
    else:
        stated = {}
        for row in rows:
            if len(row) < 2 or not re.fullmatch(r"[0-9]+", row[0]):
                report(f"설계서: 레벨 표의 레벨은 0 이상의 정수다: {' | '.join(row)}")
                continue
            for no in re.findall(r"[0-9]{2,}", row[1]):
                if no in stated:
                    report(f"설계서: 레벨 표에 {no}장이 두 번 나온다")
                stated[no] = int(row[0])
        computed = levels(graph)
        for no in sorted(contracts):
            if no not in stated:
                report(f"설계서: 레벨 표에 {no}장이 없다")
            elif no in computed and stated[no] != computed[no]:
                report(f"설계서: 레벨 표의 {no}장은 레벨 {stated[no]}인데 선수챕터로 계산하면 {computed[no]}이다")
        for no in sorted(stated.keys() - contracts.keys()):
            report(f"설계서: 레벨 표의 {no}장은 계약이 없다")
    rows = table(text, "용어집", ("용어", "표기", "최초 정의 챕터"))
    if rows is None:
        report("설계서: 「용어집」에 `용어 | 표기 | 최초 정의 챕터` 표가 없다")
    for row in rows or ():
        m = re.fullmatch(r"([0-9]{2,})장?", row[2]) if len(row) >= 3 else None
        if not all(row[:2]) or not m or m.group(1) not in contracts:
            report(f"설계서: 용어집 행에 빈 칸이 있거나 최초 정의 챕터가 계약 번호가 아니다: {' | '.join(row)}")
    rows = table(text, "원래 목차에서 바꾼 것", ("바꾼 것", "원래", "이유"))
    if not rows:
        report("설계서: 「원래 목차에서 바꾼 것」에 `바꾼 것 | 원래 | 이유` 표와 행이 없다 (없으면 `없음` 한 행)")
    for row in rows or ():
        if len(row) < 3 or not row[0] or row[2] in ("", "-", "—"):
            report(f"설계서: 「원래 목차에서 바꾼 것」의 행에 이유가 없다: {' | '.join(row)}")


def check_design_reviews(root, reports, report, stage):
    """두 축 설계 검수 리포트(산출물 계약 3절 「설계 검수 리포트」). 둘 다 없으면 report로 알린다.

    남은 S2·S3·미확인은 design과 final에서만 알린다 — 집필 중에는 이미 본 경고다."""
    if not reports:
        report("설계 검수 리포트가 없다. 검수/설계-정확성.md·설계-독자.md가 필요하다")
        return
    if sorted(str(r[1].get("축")) for r in reports) != sorted(AXES):
        err("설계 검수: 정확성·독자 리포트가 각각 하나씩 필요하다")
    current, histories = tree_hash(root / DESIGN_DIR), {}
    for rp, rfm in reports:
        axis = rfm.get("축")
        if rfm.get("대상") != DESIGN_DIR or rp.name != f"{DESIGN}-{axis}.md":
            err(f"{rp.name}: 대상이 `{DESIGN_DIR}`가 아니거나 검수 축이 다르다")
        if rfm.get("대상해시") != current:
            err(f"{rp.name}: 검수한 설계와 현재 {DESIGN_DIR}가 다르다 — 설계 재검수 필요")
        counts, findings, unknowns, history = parse_report(rp, rfm, design=True)
        if history is not None:
            histories[axis] = history
        if counts["S1"]:
            ids = ", ".join(i for i, (s, _) in sorted(findings.items()) if s == "S1")
            err(f"{rp.name}: 미해결 S1 {ids} — 설계자에게 재설계를 배정한다")
        if stage not in ("design", "final"):
            continue
        for key in ("S2", "S3"):
            if counts[key]:
                warn(f"{rp.name}: {key} {counts[key]}건 남음")
        if unknowns:
            warn(f"{rp.name}: 미확인 {len(unknowns)}건 — 계약의 「근거 확인 필요 항목」으로 넘긴다")
    for reason in tally_design(histories)["막힘"]:
        err(f"설계: 상한 도달 — {reason}. 사용자에게 넘긴다")


MARKER = "<!-- 확인 필요"


def markers(p):
    """원고의 `확인 필요` 표시 — (줄 번호, 표시만 있는 줄인가). 위치 표기처럼 frontmatter부터 센다."""
    text = p.read_text(encoding="utf-8")
    offset = text[:len(text) - len(body(p))].count("\n")
    return [(ln + offset, not re.sub(r"<!--.*?-->", "", line).strip())
            for ln, line in unfenced(body(p)) if MARKER in line]


def answered(rp):
    """정확성 리포트가 짚은 원고 줄 — 「근거 확인」의 `- L<n>`, 지적 표·「미확인」 표의 위치."""
    text, lines = body(rp), set()
    def add(where):
        for a, b in re.findall(r"L([0-9]+)(?:-L([0-9]+))?", where):
            lines.update(range(int(a), int(b or a) + 1))
    for line in section(text, "근거 확인"):
        m = re.match(r"^\s*[-*]\s*(?:\*\*)?\s*(L[0-9]+(?:-L[0-9]+)?(?:\s*[,·]\s*L[0-9]+(?:-L[0-9]+)?)*)", line)
        if m:
            add(m.group(1))
    for _, line in unfenced(text):
        row = cells(line) if line.lstrip().startswith("|") else []
        if len(row) > 3 and re.fullmatch(r"S[123]-[0-9]+", row[0]):
            add(row[3])
        elif len(row) > 1 and re.fullmatch(r"U-[0-9]+", row[0]):
            add(row[1])
    return lines


def check_markers(p, report, stage):
    """`확인 필요` 표시마다 현재 정확성 리포트가 답했는지 본다(산출물 계약 3절 「확인 필요 표시」)."""
    lines = answered(report)
    for ln, alone in markers(p):
        if ln not in lines and not (alone and ln + 1 in lines):
            err(f"{p.name} L{ln}: 확인 필요 표시에 {report.name}가 답하지 않았다 — 정확성 재검수 필요")
        elif stage == "final":
            err(f"{p.name} L{ln}: 확인 필요 표시가 남아 있다 — {report.name}가 답했으니 편집자가 지운다")
        else:
            warn(f"{p.name} L{ln}: 확인 필요 표시 — {report.name}가 답했다. 재집필하는 집필자나 첫 편집 라운드의 편집자가 지운다")


def check(root: Path, stage="final", selected=None):
    if not root.is_dir():
        err(f"출력 경로가 없다: {root}")
        return
    if stage == "intake":
        intake(root)
        return
    contracts, chapters, reviews = load_book(root)
    if not contracts:
        err("챕터 계약이 없다. Phase 1이 끝나지 않았다")
        return

    if not (root / "00-설계/설계서.md").is_file():
        err("설계서가 없다")
    graph = {}
    declared = set()
    for no, (p, fm) in contracts.items():
        for key in ("제목", "슬러그", "분량", "읽기시간"):
            if not isinstance(fm.get(key), str) or not fm[key].strip():
                err(f"{p.name}: 계약 필드 `{key}` 누락")
        if p.name != f"{no}.md" or not positive(fm.get("계약버전")):
            err(f"{p.name}: 계약 파일명 또는 계약버전이 잘못됐다")
        for key in ("목차항목", "선수챕터"):
            if not isinstance(fm.get(key), list):
                err(f"{p.name}: `{key}` 목록 누락")
        items = fm.get("목차항목", [])
        if isinstance(items, list):
            declared.update(items)
        deps = fm.get("선수챕터", [])
        graph[no] = deps if isinstance(deps, list) else []
        for dep in graph[no]:
            if dep not in contracts or dep == no:
                err(f"{no}장: 존재하지 않거나 자기 자신인 선수챕터 {dep}")

    visiting, visited = set(), set()
    def visit(no):
        if no in visiting:
            err(f"의존성 순환: {no}장")
            return
        if no in visited:
            return
        visiting.add(no)
        for dep in graph.get(no, []):
            visit(dep)
        visiting.remove(no)
        visited.add(no)
    for no in graph:
        visit(no)

    # 목차 항목 누락
    items = toc_items(root)
    if items is not None:
        for item in sorted(items - declared):
            err(f"목차 {item} 항목이 어느 계약에도 배정되지 않았다")
        for item in sorted(declared - items):
            err(f"계약의 목차항목 {item}이 목차.md에 없다")

    # 설계를 고칠 비용이 가장 싼 원고 전에는 막고, 집필이 시작된 책에는 알리기만 한다.
    check_design(root, contracts, graph, warn if chapters else err)

    if stage == "plan":
        return
    # 원고가 생기기 전에 설계 검수를 요구하고, 이 규칙 전에 집필이 시작된 책에는 알리기만 한다.
    check_design_reviews(root, reviews.get(DESIGN, []), warn if chapters else err, stage)
    if stage == "design":
        return
    wanted = set(selected or contracts)
    for no in wanted - contracts.keys():
        err(f"{no}장: 계약이 없다")
    # 부분 검증도 선수의 낡은 입력을 건너뛰지 않는다.
    pending = list(wanted)
    while pending:
        for dep in graph.get(pending.pop(), []):
            if dep not in wanted:
                wanted.add(dep)
                pending.append(dep)
    for no in wanted - chapters.keys():
        err(f"{no}장: 원고가 없다 (미집필)")
    for no in chapters.keys() - contracts.keys():
        err(f"{no}장: 대응하는 계약이 없다")
    for no in reviews.keys() - contracts.keys() - {DESIGN}:
        err(f"{no}장: 대응하는 계약이 없는 검수 리포트")
    acceptances = accepted(root) if stage == "final" else set()
    marked = set()
    for no in sorted(wanted & chapters.keys() & contracts.keys()):
        p, fm = chapters[no]
        cp, cf = contracts[no]
        if p.name != f"{no}-{cf.get('슬러그')}.md":
            err(f"{p.name}: 계약의 번호·슬러그와 파일명이 다르다")
        if not positive(fm.get("계약버전")) or fm.get("계약버전") != cf.get("계약버전"):
            err(f"{no}장: 계약버전이 없거나 현재 계약과 다르다")
        if not isinstance(fm.get("요약"), str) or not fm["요약"].strip():
            err(f"{no}장: frontmatter `요약`이 비었다")
        if not body(p).strip():
            err(f"{no}장: 본문이 비었다")
        size, length = size_range(cf.get("분량")), len(body(p))
        if size and not size[0] <= length <= size[1]:
            warn(f"{p.name}: 본문 {length}자 — 계약 분량 {cf['분량']} 밖")
        asked = len(questions(body(cp)))
        heads = [line for _, line in unfenced(body(p))
                 if re.match(r"^##\s", line) and line[2:].strip() != WRAP_UP]
        if asked and len(heads) != asked:
            warn(f"{p.name}: `##` 소제목 {len(heads)}개 — 계약 질문 {asked}개와 다르다")
        try:
            if fm.get("입력해시") != input_hash(root, no, contracts, chapters):
                err(f"{no}장: 입력해시가 없거나 계약·설계·선수 요약이 바뀌었다 — stale")
        except (OSError, ValueError) as exc:
            err(str(exc))
        if stage in ("review", "final"):
            reports = reviews.get(no, [])
            axes = [r[1].get("축") for r in reports]
            if sorted(str(a) for a in axes) != sorted(AXES):
                err(f"{no}장: 정확성·독자 리포트가 각각 하나씩 필요하다")
            histories = {}
            for rp, rfm in reports:
                if not body(rp).strip():
                    err(f"{rp.name}: 검수 리포트 본문이 비었다")
                if (rfm.get("대상") != p.relative_to(root).as_posix()
                        or rp.name != f"{no}-{rfm.get('축')}.md"):
                    err(f"{rp.name}: 대상 경로 또는 검수 축이 다르다")
                if rfm.get("대상해시") != sha256(p):
                    err(f"{rp.name}: 검수한 판본과 현재 원고가 다르다 — 재검수 필요")
                if (rfm.get("계약버전") != cf.get("계약버전")
                        or rfm.get("계약해시") != sha256(cp)):
                    err(f"{rp.name}: 계약 판본이 다르다 — 재검수 필요")
                axis, recorded = rfm.get("축"), rfm.get("검수입력해시")
                if not isinstance(recorded, str) or not recorded.startswith(f"{REVIEW_INPUTS}:"):
                    err(f"{rp.name}: 검수입력해시가 없거나 축을 나누기 전 v1 값이다 — 재검수 필요")
                elif axis in AXES:
                    try:
                        if recorded != review_input_hash(root, no, contracts, chapters, axis):
                            changed = "설계·계약" if axis == "정확성" else "설계·선수 본문"
                            err(f"{rp.name}: 검수입력해시가 다르다. {changed}이 바뀌었다 — 재검수 필요")
                    except (OSError, ValueError) as exc:
                        err(str(exc))
                counts, findings, unknowns, history = parse_report(rp, rfm)
                if history is not None:
                    histories[axis] = history
                for key, count in counts.items():
                    value = rfm.get(key)
                    if count or (isinstance(value, str) and value.isdigit() and int(value)):
                        if key == "S1":
                            owned = [i for i, (s, o) in sorted(findings.items()) if s == "S1" and o == "계약"]
                            err(f"{rp.name}: 미해결 S1 — 통과 불가"
                                + (f". 계약 귀속 {', '.join(owned)}은 설계자에게" if owned else ""))
                        else:
                            warn(f"{rp.name}: {key} {value}건 남음")
                if unknowns and stage == "review":
                    warn(f"{rp.name}: 미확인 {len(unknowns)}건 — final 전에 사용자 수락 필요")
                for identity in unknowns if stage == "final" else ():
                    if (f"{no}/{axis}/{identity}", rfm.get("대상해시")) not in acceptances:
                        err(f"{rp.name}: 미확인 {identity}이 이 판본으로 수락되지 않았다 — 사용자 결정 필요")
            fresh = [rp for rp, rfm in reports if rfm.get("축") == "정확성" and rfm.get("대상해시") == sha256(p)]
            if fresh:
                check_markers(p, fresh[0], stage)
                marked.add(p)
            for reason in tally_chapter(no, histories, cf.get("계약버전"))["막힘"]:
                err(f"{no}장: 상한 도달 — {reason}. blocked로 두고 사용자에게 넘긴다")

    index = root / "index.md"
    if stage == "final" and (not index.is_file() or not body(index).strip()):
        err("최종 인계에는 비어 있지 않은 index.md가 필요하다")

    # 링크·앵커
    paths = [chapters[no][0] for no in sorted(wanted & chapters.keys())]
    if stage == "final":
        paths.append(index)
    index_links = set()
    planned = {(root / "chapters" / f"{no}-{fm.get('슬러그')}.md").resolve(): no
               for no, (_, fm) in contracts.items()}
    for p in paths:
        if not p.is_file():
            continue
        for ln, line in unfenced(body(p)):
            for part in prose_parts(line)[::2]:
                if re.search(r"^\s*\[[^]]+\]:|\]\s*\[", part):
                    err(f"{p.name}:{ln}: 참조형 링크 대신 인라인 링크를 사용한다")
                for match in LINK.finditer(part):
                    target = match.group(1)
                    local = local_target(p, target)
                    if local is None:
                        continue
                    dest, anchor = local
                    if p == index:
                        index_links.add(dest)
                    if not dest.is_file():
                        if selected and stage != "final" and dest in planned and planned[dest] not in wanted:
                            warn(f"{p.name}:{ln} 미집필 후행 링크, 최종 단계에서 확인: {target}")
                        else:
                            err(f"{p.name}:{ln} 링크 대상이 없다: {target}")
                    elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                        err(f"{p.name}:{ln} 앵커가 없다: {target}")
            if stage == "final" and MARKER in line and p not in marked:
                err(f"{p.name}:{ln}: 확인 필요 표시가 남아 있다")
    if stage == "final" and index.is_file():
        for p, _ in chapters.values():
            if p.resolve() not in index_links:
                err(f"index.md: {p.name} 링크 누락")

    # 형광펜 개수 (소단원당 3개 이내)
    for p in paths:
        if not p.is_file() or p == index:
            continue
        section, count = None, 0
        def flush():
            if section and count > 3:
                warn(f"{p.name}: 「{section}」 형광펜 {count}개 (상한 3)")
        for _, line in unfenced(body(p)):
            if re.match(r"^#{2,3}\s+", line):
                flush()
                section, count = line.lstrip("# ").strip(), 0
            elif not line.lstrip().startswith(">"):
                count += sum(len(re.findall(r"<mark|🟡|🟢|🔴", part))
                             for part in prose_parts(line)[::2])
        flush()


# ---------------------------------------------------------------- build

GENERATED = "<!-- Generated by ai-harness book.py; do not edit. -->"


def build(root: Path, out: Path):
    check(root, "final")
    if ERR:
        return
    _, chapters, _ = load_book(root)
    out = out.absolute()
    # 합본은 책 루트의 재생성물만 덮어쓴다. 소스·사용자 문서·링크는 보존한다.
    if (out.parent.resolve() != root.resolve() or out.suffix != ".md" or out.is_symlink()
            or out.name in ("index.md", "목차.md")
            or (out.exists() and not out.read_text(encoding="utf-8").startswith(GENERATED))):
        err("합본은 책 루트의 새 .md 파일 또는 이 도구가 생성한 합본 경로여야 한다")
        return
    title = root.name
    idx = root / "index.md"
    if idx.is_file():
        for _, line in unfenced(idx.read_text(encoding="utf-8")):
            if line.startswith("# "):
                title = line[2:].strip()
                break

    parts = [f"{GENERATED}\n\n# {title}\n"]
    toc = ["## 목차\n"]
    chapter_paths = {p.resolve(): no for no, (p, _) in chapters.items()}
    for no in sorted(chapters, key=int):
        p, fm = chapters[no]
        name = fm.get("제목") or p.stem
        toc.append(f"- [{no}. {name}](#ch{no})")
        parts.append(f'\n<a id="ch{no}"></a>\n')
        outside = dict(unfenced(body(p)))
        headings = heading_ids(p)
        for ln, line in enumerate(body(p).splitlines(), 1):
            if ln in outside:
                if ln in headings:
                    parts.append(f'<a id="ch{no}-{headings[ln]}"></a>')
                    if re.match(r"^#{1,5}\s", line):
                        line = "#" + line
                chunks = prose_parts(line)
                for i in range(0, len(chunks), 2):
                    def rewrite(m):
                        target = local_target(p, m.group(1))
                        if target is None:
                            return m.group(0)
                        dest, anchor = target
                        if dest in chapter_paths:
                            value = f"#ch{chapter_paths[dest]}" + (f"-{anchor}" if anchor else "")
                        else:
                            parsed = urlsplit(m.group(1).strip("<>"))
                            value = quote(os.path.relpath(dest, out.parent), safe="/-._~")
                            value += (f"?{parsed.query}" if parsed.query else "")
                            value += (f"#{parsed.fragment}" if parsed.fragment else "")
                        return m.group(0).replace(m.group(1), value, 1)
                    chunks[i] = LINK.sub(rewrite, chunks[i])
                    chunks[i] = re.sub(r'(<a\s+(?:id|name)=["\'])([^"\']+)',
                                       lambda m: m[1] + f"ch{no}-" + m[2], chunks[i])
                line = "".join(chunks)
            parts.append(line)
        parts.append("")
    content = "\n".join([parts[0], *toc, "", *parts[1:], ""])
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=out.parent,
                                         prefix=".book-", delete=False) as handle:
            tmp = Path(handle.name)
            handle.write(content)
        tmp.replace(out)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()
    print(f"합본: {out}  ({len(chapters)}장, {len(content)}자)")


# ---------------------------------------------------------------- main

def main(argv):
    ERR.clear()
    WARN.clear()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="cmd", required=True)
    for name in ("hash", "inputs", "review-inputs", "check", "tally", "build"):
        sub = commands.add_parser(name)
        sub.add_argument("path", type=Path)
        if name in ("inputs", "review-inputs"):
            sub.add_argument("number")
            if name == "review-inputs":
                sub.add_argument("axis", choices=AXES)
        elif name in ("check", "tally"):
            if name == "check":
                sub.add_argument("--stage", choices=STAGES, default="final")
                sub.add_argument("--axis", choices=AXES, help="다른 축 리포트에 관한 메시지를 뺀다")
            sub.add_argument("--chapter", action="append")
        elif name == "build":
            sub.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = args.path.expanduser().resolve()
    try:
        if args.cmd == "hash":
            print(tree_hash(root) if root.is_dir() else sha256(root))
            return 0
        if args.cmd in ("inputs", "review-inputs"):
            contracts, chapters, _ = load_book(root)
            if args.number not in contracts:
                err(f"{args.number}장: 계약이 없다")
            elif not ERR:
                if args.cmd == "inputs":
                    print(input_hash(root, args.number, contracts, chapters))
                else:
                    print(review_input_hash(root, args.number, contracts, chapters, args.axis))
                return 0
        elif args.cmd == "check":
            if args.chapter and args.stage not in ("draft", "review"):
                parser.error("--chapter는 draft/review에서만 사용할 수 있다")
            check(root, args.stage, args.chapter)
        elif args.cmd == "tally":
            result = tally(root, args.chapter)
            if not ERR:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
        elif args.cmd == "build":
            build(root, args.output.expanduser() if args.output else root / f"{root.name}.md")
    except (OSError, ValueError) as exc:
        err(str(exc))

    if getattr(args, "axis", None):
        # 검수 독립성: 다른 축 리포트의 판정·개수가 검수자에게 보이지 않게 한다.
        other = next(a for a in AXES if a != args.axis)
        for messages in (ERR, WARN):
            messages[:] = [m for m in messages if f"-{other}.md" not in m and f"/{other}/" not in m]
    for m in WARN:
        print(f"  ! {m}")
    for m in ERR:
        print(f"  ✗ {m}")
    if ERR:
        print(f"\n오류 {len(ERR)}건. 통과시키지 않는다.")
        return 1
    print(f"\n통과. 경고 {len(WARN)}건." if WARN else "\n통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
