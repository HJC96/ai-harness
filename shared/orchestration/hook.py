#!/usr/bin/env python3
"""교재 하네스 훅 — 에이전트와 `교재` 스킬의 frontmatter에서 부른다.

  hook.py pre  <역할>   PreToolUse: 검수 독립성을 깨는 쓰기를 막고, book.py 읽기 명령을 허용한다
  hook.py post <역할>   PostToolUse: 책 안의 쓰기를 .교재기록.jsonl에 남긴다
  hook.py stop <역할>   SubagentStop: 이 작업자가 쓴 파일과 배정된 파일로 book.py check를 돌려 알린다(막지 않음)

<역할>은 에이전트 이름이거나 메인 세션(main)이다. 책 작업 공간(.교재상태.json이 있는
디렉터리) 밖에서는 아무것도 하지 않는다. 막을 때만 exit 2이고, 훅 자체의 실패는
통과시킨다 — 훅은 보조 계층이고 게이트는 book.py check다.
"""
import importlib.util
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit(0)

HERE = Path(__file__).resolve().parent
STATE = ".교재상태.json"
LOG = ".교재기록.jsonl"
ACCEPTED = "미확인-수락.md"
MAIN = "main"
REVIEWERS = ("technical-reviewer", "learner-advocate")
ROLES = ("curriculum-architect", "chapter-writer", "learning-editor") + REVIEWERS
FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
              "NotebookEdit": "notebook_path"}
READ_ONLY = ("check", "inputs", "review-inputs", "tally", "hash")
# 셸이 다른 명령을 끼워 넣을 수 있는 문자가 하나라도 있으면 허용하지 않는다.
BOOK_COMMAND = re.compile(r"python3\s+(\S+)\s+([a-z-]+)(\s+[^;&|<>`$\\(){}\n\r]*)?")


def book_root(path: Path):
    for d in path.parents:
        if (d / STATE).is_file():
            return d
    return None


def target(data):
    key = FILE_TOOLS.get(data.get("tool_name"))
    raw = (data.get("tool_input") or {}).get(key) if key else None
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(os.path.normpath(os.path.join(data.get("cwd") or os.getcwd(), os.path.expanduser(raw))))
    root = book_root(path)
    if root is None:
        return None
    return root, unicodedata.normalize("NFC", path.relative_to(root).as_posix())


def denied(role, rel):
    """검수 독립성을 깨는 쓰기면 그 이유를 돌려준다. 소유권 전체가 아니라 이것만 막는다."""
    top = rel.split("/", 1)[0]
    if rel == LOG:
        return "작업 기록은 훅만 쓴다(산출물 계약 8절)"
    if role == MAIN:
        if top in ("검수", "chapters", "00-설계"):
            return (f"지휘자는 {top}/를 직접 고치지 않는다. 계약은 설계자, 본문은 집필자, "
                    "판정은 검수자에게 배정한다(파이프라인 「지휘자」)")
    elif role in REVIEWERS:
        if top != "검수" or "/" not in rel:
            return "검수자는 검수/ 밖에 쓰지 않는다. 본문·계약·상태는 읽기만 한다"
    elif top == "검수":
        return "쓴 사람이 검수하지 않는다. 검수/는 두 검수자만 쓴다"
    elif rel == ACCEPTED:
        return "미확인 수락은 사용자의 결정이라 지휘자만 적는다(산출물 계약 7절)"
    return None


def record(root, data, role, event, **extra):
    entry = {"시각": datetime.now().astimezone().isoformat(timespec="seconds"),
             "세션": data.get("session_id", ""), "에이전트": data.get("agent_id", ""),
             "역할": "지휘자" if role == MAIN else role, "사건": event}
    entry.update(extra)
    with open(root / LOG, "a", encoding="utf-8") as f:
        try:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        except (ImportError, OSError):
            pass
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def allowed_book_command(role, command):
    match = BOOK_COMMAND.fullmatch(command.strip())
    if not match:
        return False
    script, sub = match.group(1), match.group(2)
    if sub not in READ_ONLY and not (role == MAIN and sub == "build"):
        return False
    try:
        return Path(os.path.expanduser(script)).resolve() == (HERE / "book.py").resolve()
    except OSError:
        return False


def pre(role, data):
    if data.get("tool_name") == "Bash":
        command = (data.get("tool_input") or {}).get("command")
        if isinstance(command, str) and allowed_book_command(role, command):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow",
                "permissionDecisionReason": "교재 하네스: book.py 점검 명령"}}, ensure_ascii=False))
        return 0
    found = target(data)
    if not found:
        return 0
    root, rel = found
    reason = denied(role, rel)
    if not reason:
        return 0
    try:
        record(root, data, role, "차단", 도구=data.get("tool_name"), 경로=rel, 사유=reason)
    except OSError:
        pass  # 기록을 못 남겨도 막는 것은 막는다
    print(f"교재 하네스 훅이 막았다: {rel} — {reason}.", file=sys.stderr)
    return 2


def post(role, data):
    found = target(data)
    if found:
        record(found[0], data, role, "쓰기", 도구=data.get("tool_name"), 경로=found[1])
    return 0


def written(transcript):
    """작업자 대화 기록에서 Write·Edit가 받은 경로를 모은다."""
    paths = []
    def walk(node):
        if isinstance(node, dict):
            key = FILE_TOOLS.get(node.get("name"))
            value = (node.get("input") or {}).get(key) if node.get("type") == "tool_use" and key else None
            if isinstance(value, str):
                paths.append(value)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
    with open(transcript, encoding="utf-8") as f:
        for line in f:
            try:
                walk(json.loads(line))
            except ValueError:
                continue
    return paths


def assignment(transcript):
    """작업자 대화의 첫 메시지(배정 메시지)와 그 시각. 없으면 ("", None)."""
    with open(transcript, encoding="utf-8") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "user":
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content
                                    if isinstance(c, dict) and c.get("type") == "text")
            started = None
            try:
                started = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00")).timestamp()
            except (KeyError, AttributeError, ValueError):
                pass
            return (content if isinstance(content, str) else ""), started
    return "", None


def assigned(message, cwd):
    """배정 메시지 `쓸 수 있는 파일` 칸의 경로(산출물 계약 6절). `/`로 끝나면 그 아래 전부."""
    fields, key = {}, None
    for line in message.splitlines():
        m = re.match(r"^([^\s:][^:]{0,20}):\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            fields[key] = [m.group(2)]
        elif key and line.strip():
            fields[key].append(line.strip())
    base = (fields.get("작업 공간") or [cwd or os.getcwd()])[0].split("←")[0].strip()
    paths = []
    for value in fields.get("쓸 수 있는 파일", []):
        value = re.sub(r"\([^)]*\)", " ", value.split("←")[0])
        for token in re.split(r"[,\s]+", value):
            if not token or not re.search(r"\.[A-Za-z]+$|/$", token):
                continue
            path = Path(os.path.join(base, os.path.expanduser(token)))
            if token.endswith("/") and path.is_dir():
                paths += [str(f) for f in sorted(path.rglob("*"))
                          if f.is_file() and not any(part.startswith(".") for part in f.relative_to(path).parts)]
            else:
                paths.append(str(path))
    return paths


def load_book_module():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("book", HERE / "book.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stop_checks(role, rels):
    """역할과 쓴 파일로 돌릴 (stage, 챕터, 남길 메시지의 표지)을 정한다.

    선수 챕터나 다른 축처럼 이 작업자의 몫이 아닌 메시지는 표지로 거른다."""
    numbers = lambda folder: sorted({m.group(1) for r in rels
                                     for m in [re.match(rf"{folder}/([0-9]{{2}})-", r)] if m})
    if role == "curriculum-architect":
        return [("plan", None, None)] if any(r.startswith("00-설계/") for r in rels) else []
    if role in ("chapter-writer", "learning-editor"):
        chapters = numbers("chapters")
        marks = tuple(f"{no}장" for no in chapters) + tuple(Path(r).name for r in rels
                                                           if r.startswith("chapters/"))
        return [("draft", chapters, marks)] if chapters else []
    if role in REVIEWERS:
        design = [Path(r).name for r in rels if r.startswith("검수/설계-")]
        return [("review", [no], (Path(r).name,)) for no in numbers("검수")
                for r in rels if r.startswith(f"검수/{no}-")] + ([("design", None, tuple(design))] if design else [])
    return []


def stop(role, data):
    transcript = data.get("agent_transcript_path")
    if not transcript or not os.path.isfile(transcript):
        return 0
    books, unseen = {}, []
    resolve = lambda raw: target({"tool_name": "Write", "tool_input": {"file_path": raw}, "cwd": data.get("cwd")})
    for raw in written(transcript):
        found = resolve(raw)
        if found:
            books.setdefault(found[0], set()).add(found[1])
    # Bash로 고친 배정 파일도 점검에서 빠지지 않게 배정 메시지의 쓰기 대상을 더한다.
    message, started = assignment(transcript)
    for raw in assigned(message, data.get("cwd")):
        found = resolve(raw)
        if not found or not (found[0] / found[1]).is_file():
            continue
        if found[1] not in books.get(found[0], set()) and started and (found[0] / found[1]).stat().st_mtime >= started:
            unseen.append(found)
        books.setdefault(found[0], set()).add(found[1])
    if not books:
        return 0
    for root, rel in unseen:
        record(root, data, role, "쓰기", 도구="미상", 경로=rel)
    book = load_book_module()
    lines = []
    for root, rels in books.items():
        errors = warnings = 0
        messages = []
        for stage, chapters, marks in stop_checks(role, rels):
            book.ERR.clear()
            book.WARN.clear()
            try:
                book.check(root, stage, chapters)
            except (OSError, ValueError) as exc:
                book.err(str(exc))
            keep = lambda ms: [m for m in ms if marks is None or any(k in m for k in marks)]
            errors += len(keep(book.ERR))
            warnings += len(keep(book.WARN))
            messages += [f"  ✗ {m}" for m in keep(book.ERR)] + [f"  ! {m}" for m in keep(book.WARN)]
        result = f"오류 {errors} · 경고 {warnings}"
        missed = [rel for r, rel in unseen if r == root]
        if missed:
            messages.insert(0, f"  ! Write·Edit 밖에서 바뀐 배정 파일: {', '.join(missed)} — 기록에 `미상`으로 남겼다")
        record(root, data, role, "종료점검", 결과=result, 메시지=messages)
        if messages:
            lines.append(f"{root.name}: {result}")
            lines += messages[:8] + ([f"  … {len(messages) - 8}건 더"] if len(messages) > 8 else [])
    if lines:
        print(json.dumps({"systemMessage": f"교재 훅 종료 점검({role}) — 막지 않는다\n" + "\n".join(lines)},
                         ensure_ascii=False))
    return 0


def main(argv):
    if len(argv) != 2 or argv[0] not in ("pre", "post", "stop") or argv[1] not in ROLES + (MAIN,):
        print("사용법: hook.py pre|post|stop <역할|main>", file=sys.stderr)
        return 1
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    mode, role = argv
    # 스킬 훅이 작업자의 도구 호출에도 걸리면 작업자 자신의 훅에 맡긴다.
    if role == MAIN and data.get("agent_type"):
        return 0
    try:
        return {"pre": pre, "post": post, "stop": stop}[mode](role, data)
    except Exception as exc:  # 훅의 실패가 작업을 막지 않는다
        print(f"교재 하네스 훅 오류(무시함): {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
