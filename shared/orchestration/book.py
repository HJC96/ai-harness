#!/usr/bin/env python3
"""교재 산출물 점검·합본 도구.

  python3 shared/orchestration/book.py check <출력경로> --stage plan|draft|review|final
  python3 shared/orchestration/book.py build <출력경로> [합본경로]
  python3 shared/orchestration/book.py hash <파일>
  python3 shared/orchestration/book.py inputs <출력경로> <챕터번호>
  python3 shared/orchestration/book.py review-inputs <출력경로> <챕터번호>

판단은 하지 않는다. 기계로 확인할 수 있는 것만 본다 —
계약 버전 일치, 검수 판정의 신선도, 링크·앵커, 목차 항목 누락, 형광펜 개수.
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

ERR, WARN = [], []
def err(m): ERR.append(m)
def warn(m): WARN.append(m)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frontmatter(path: Path) -> dict:
    """문서 계약의 YAML 부분집합. 지원하지 않는 문법은 조용히 무시하지 않는다."""
    text = path.read_text(encoding="utf-8")
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

def load_book(root: Path):
    contracts, chapters, reviews = {}, {}, {}
    for directory, target in ((root / "00-설계/챕터계약", contracts),
                              (root / "chapters", chapters), (root / "검수", reviews)):
        for p in sorted(directory.glob("*.md")):
            try:
                fm = frontmatter(p)
                no = p.stem.split("-")[0] if target is reviews else fm.get("번호", "")
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


def review_input_hash(root, no, contracts, chapters):
    """독자 검수자는 선수 본문도 읽는다. 요약이 같아도 본문 변경은 판정을 무효화한다."""
    snapshot = {"설계": sha256(root / "00-설계/설계서.md"), "선수본문": {}}
    deps = contracts[no][1].get("선수챕터")
    if not isinstance(deps, list):
        raise ValueError(f"{no}장: 선수챕터 목록이 없다")
    for dep in deps:
        if dep not in chapters:
            raise ValueError(f"{no}장: 선수 {dep}장 원고가 없다")
        snapshot["선수본문"][dep] = sha256(chapters[dep][0])
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def positive(value):
    return isinstance(value, str) and re.fullmatch(r"[1-9][0-9]*", value)


def check(root: Path, stage="final", selected=None):
    if not root.is_dir():
        err(f"출력 경로가 없다: {root}")
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
    toc = root / "목차.md"
    if not toc.is_file():
        err("목차.md가 없다. 번호를 붙인 원문 목차가 필요하다")
    else:
        items = set()
        for _, line in unfenced(toc.read_text(encoding="utf-8")):
            m = re.match(r"^\s*(?:#{1,6}\s+|[-*]\s+)?(\d+(?:\.\d+)*)(?:[.)]?\s+)", line)
            if m:
                items.add(m.group(1))
        if not items:
            err("목차.md에 검사 가능한 번호 항목이 없다")
        for item in sorted(items - declared):
            err(f"목차 {item} 항목이 어느 계약에도 배정되지 않았다")
        for item in sorted(declared - items):
            err(f"계약의 목차항목 {item}이 목차.md에 없다")

    if stage == "plan":
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
    for no in reviews.keys() - contracts.keys():
        err(f"{no}장: 대응하는 계약이 없는 검수 리포트")
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
        try:
            if fm.get("입력해시") != input_hash(root, no, contracts, chapters):
                err(f"{no}장: 입력해시가 없거나 계약·설계·선수 요약이 바뀌었다 — stale")
        except (OSError, ValueError) as exc:
            err(str(exc))
        if stage in ("review", "final"):
            try:
                context_hash = review_input_hash(root, no, contracts, chapters)
            except (OSError, ValueError) as exc:
                err(str(exc))
                context_hash = None
            reports = reviews.get(no, [])
            axes = [r[1].get("축") for r in reports]
            if sorted(str(a) for a in axes) != sorted(["정확성", "독자"]):
                err(f"{no}장: 정확성·독자 리포트가 각각 하나씩 필요하다")
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
                if context_hash is None or rfm.get("검수입력해시") != context_hash:
                    err(f"{rp.name}: 검수입력해시가 없거나 설계·선수 본문이 바뀌었다 — 재검수 필요")
                counts, ids = {"S1": 0, "S2": 0, "S3": 0}, set()
                for _, line in unfenced(body(rp)):
                    m = re.match(r"^\|\s*(S[123]-\d+)\s*\|\s*(S[123]|해결)\s*\|", line)
                    if re.match(r"^\|\s*S[123]-", line) and not m:
                        err(f"{rp.name}: 잘못된 지적 ID 또는 심각도 행")
                    if m:
                        identity, severity = m.groups()
                        if identity in ids:
                            err(f"{rp.name}: 지적 ID 중복 {identity}")
                        ids.add(identity)
                        if severity in counts:
                            counts[severity] += 1
                for key, count in counts.items():
                    value = rfm.get(key)
                    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
                        err(f"{rp.name}: `{key}`는 0 이상의 정수여야 한다")
                    elif int(value) != count:
                        err(f"{rp.name}: `{key}` 개수와 지적 표가 다르다")
                    if count or (isinstance(value, str) and value.isdigit() and int(value)):
                        if key == "S1":
                            err(f"{rp.name}: 미해결 S1 — 통과 불가")
                        else:
                            warn(f"{rp.name}: {key} {value}건 남음")

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
            if stage == "final" and "<!-- 확인 필요" in line:
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
                count += len(re.findall(r"<mark|🟡|🟢|🔴", line))
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
    for name in ("hash", "inputs", "review-inputs", "check", "build"):
        sub = commands.add_parser(name)
        sub.add_argument("path", type=Path)
        if name in ("inputs", "review-inputs"):
            sub.add_argument("number")
        elif name == "check":
            sub.add_argument("--stage", choices=("plan", "draft", "review", "final"), default="final")
            sub.add_argument("--chapter", action="append")
        elif name == "build":
            sub.add_argument("output", nargs="?", type=Path)
    args = parser.parse_args(argv)
    root = args.path.expanduser().resolve()
    try:
        if args.cmd == "hash":
            print(sha256(root))
            return 0
        if args.cmd in ("inputs", "review-inputs"):
            contracts, chapters, _ = load_book(root)
            if args.number not in contracts:
                err(f"{args.number}장: 계약이 없다")
            elif not ERR:
                hasher = input_hash if args.cmd == "inputs" else review_input_hash
                print(hasher(root, args.number, contracts, chapters))
                return 0
        elif args.cmd == "check":
            if args.chapter and args.stage not in ("draft", "review"):
                parser.error("--chapter는 draft/review에서만 사용할 수 있다")
            check(root, args.stage, args.chapter)
        elif args.cmd == "build":
            build(root, args.output.expanduser() if args.output else root / f"{root.name}.md")
    except (OSError, ValueError) as exc:
        err(str(exc))

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
