#!/usr/bin/env bash
# Claude Code 하네스 설치 — 이 저장소의 원본을 ~/.claude 로 심볼릭 링크한다.
#
#   bash scripts/install-claude.sh           설치
#   bash scripts/install-claude.sh --check    상태만 확인 (쓰지 않음)
#   bash scripts/install-claude.sh --dry-run  할 일만 출력
#   bash scripts/install-claude.sh --uninstall 이 하네스가 만든 링크만 제거
#   bash scripts/install-claude.sh --doctor   하네스 자체 점검 (이름·경로 정합성)
#
# 원본은 저장소에 남고 ~/.claude 에는 링크만 생긴다. 저장소에서 파일을 고치면
# 즉시 반영된다. 이미 있는 실제 파일·디렉터리는 절대 덮어쓰지 않는다.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_HOME="${CLAUDE_CONFIG_DIR:-${CLAUDE_HOME:-$HOME/.claude}}"

SKILLS=(교재 교재-설계 챕터-집필 챕터-검수 교재-엮기)
AGENTS=(curriculum-architect chapter-writer technical-reviewer learner-advocate learning-editor)
ORCH=(교재-파이프라인.md 산출물-계약.md book.py)

MODE=install
if [[ $# -gt 1 ]]; then echo "옵션은 한 번에 하나만 지정한다." >&2; exit 2; fi
for arg in "$@"; do
  case "$arg" in
    --check) MODE=check ;;
    --dry-run) MODE=dry ;;
    --uninstall) MODE=uninstall ;;
    --doctor) MODE=doctor ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "모르는 옵션: $arg" >&2; exit 2 ;;
  esac
done

problems=0
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
skip() { printf '  \033[33m•\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; problems=$((problems+1)); }

link_one() {
  local src="$1" dest="$2" label="$3"
  if [[ ! -e "$src" ]]; then bad "$label — 원본 없음: $src"; return; fi

  if [[ -L "$dest" ]]; then
    local cur; cur="$(readlink "$dest")"
    if [[ "$cur" == "$src" ]]; then ok "$label"; else bad "$label — 다른 곳을 가리킴: $cur"; fi
    return
  fi
  if [[ -e "$dest" ]]; then bad "$label — 실제 파일이 이미 있어 건너뜀: $dest"; return; fi

  case "$MODE" in
    check) bad "$label — 미설치" ;;
    dry)   skip "$label — 설치 예정: $dest" ;;
    install) ln -s "$src" "$dest"; ok "$label — 연결함" ;;
  esac
}

unlink_one() {
  local src="$1" dest="$2" label="$3"
  if [[ -L "$dest" && "$(readlink "$dest")" == "$src" ]]; then
    rm "$dest"; ok "$label — 링크 제거"
  elif [[ -e "$dest" ]]; then
    skip "$label — 이 하네스가 만든 링크가 아니라 그대로 둠"
  else
    skip "$label — 없음"
  fi
}

doctor() {
  # 설치 전에도 실행 가능. 이 하네스의 문서와 원본만 검사한다.
  python3 - "$REPO" <<'PY'
import importlib.util
import re
import sys
from pathlib import Path
sys.dont_write_bytecode = True
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("book", root / "shared/orchestration/book.py")
book = importlib.util.module_from_spec(spec)
spec.loader.exec_module(book)
skills = ["교재", "교재-설계", "챕터-집필", "챕터-검수", "교재-엮기"]
roles = {"curriculum-architect": "교재-설계", "chapter-writer": "챕터-집필",
         "technical-reviewer": "챕터-검수", "learner-advocate": "챕터-검수",
         "learning-editor": "교재-엮기"}
paths = {"skills": root / "shared/skills", "agents": root / "claude/agents",
         "instructions": root / "shared/instructions", "orchestration": root / "shared/orchestration"}
errors, docs = [], []
for name, path in ([(s, paths["skills"] / s / "SKILL.md") for s in skills]
                   + [(a, paths["agents"] / (a + ".md")) for a in roles]):
    docs.append(path)
    try:
        fm = book.frontmatter(path)
        if fm.get("name") != name or not fm.get("description"):
            errors.append(f"{path}: name/description 누락 또는 불일치")
        if name in roles and fm.get("skills") != [roles[name]]:
            errors.append(f"{path}: 역할에 맞는 스킬을 preload해야 한다")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
docs += list((root / "shared/orchestration").glob("*.md"))
docs += [root / "shared/instructions/교재-공통규약.md", root / "claude/CLAUDE.md"]
for path in docs:
    if not path.is_file():
        errors.append(f"원본 없음: {path}")
        continue
    for ref in re.findall(r'~/\.claude/([^`\s)]+)', path.read_text(encoding="utf-8")):
        ref = ref.rstrip(".,")
        if "*" in ref:
            continue
        top, _, tail = ref.partition("/")
        if top in paths and not (paths[top] / tail).exists():
            errors.append(f"{path.name}: 참조 원본 없음: {ref}")
for error in errors:
    print(f"  ✗ {error}")
print(f"Claude 하네스 원본 검사: {'실패' if errors else '통과'}")
sys.exit(bool(errors))
PY
}

if [[ "$MODE" == "doctor" ]]; then
  echo "저장소: $REPO"; echo
  doctor
  exit 0
fi

# 어떤 링크도 만들거나 지우기 전에 전체 경로와 원본을 확인한다.
legacy=false
if [[ -L "$CLAUDE_HOME/orchestration" && "$(readlink "$CLAUDE_HOME/orchestration")" == "$REPO/shared/orchestration" ]]; then
  legacy=true
fi
for dir in "$CLAUDE_HOME" "$CLAUDE_HOME/skills" "$CLAUDE_HOME/agents" "$CLAUDE_HOME/instructions" "$CLAUDE_HOME/orchestration"; do
  if [[ "$dir" == "$CLAUDE_HOME/orchestration" && "$legacy" == true ]]; then continue; fi
  if [[ -L "$dir" || ( -e "$dir" && ! -d "$dir" ) ]]; then
    bad "설치 부모 경로가 디렉터리가 아니거나 다른 링크다: $dir"
  fi
done
[[ $problems -eq 0 ]] || exit 1

preflight() {
  local src="$1" dest="$2"
  [[ -e "$src" ]] || bad "원본 없음: $src"
  if [[ "$legacy" == true && "$dest" == "$CLAUDE_HOME/orchestration/"* ]]; then return; fi
  if [[ -L "$dest" ]]; then
    [[ "$(readlink "$dest")" == "$src" ]] || bad "다른 링크 보존: $dest"
  elif [[ -e "$dest" ]]; then
    bad "기존 파일 보존: $dest"
  fi
}
if [[ "$MODE" != uninstall ]]; then
  for s in "${SKILLS[@]}"; do
    preflight "$REPO/shared/skills/$s" "$CLAUDE_HOME/skills/$s"
    [[ -f "$REPO/shared/skills/$s/SKILL.md" ]] || bad "SKILL.md 없음: $s"
  done
  for a in "${AGENTS[@]}"; do preflight "$REPO/claude/agents/$a.md" "$CLAUDE_HOME/agents/$a.md"; done
  for o in "${ORCH[@]}"; do preflight "$REPO/shared/orchestration/$o" "$CLAUDE_HOME/orchestration/$o"; done
  preflight "$REPO/shared/instructions/교재-공통규약.md" "$CLAUDE_HOME/instructions/교재-공통규약.md"
  [[ $problems -eq 0 ]] || exit 1
fi
if [[ "$MODE" == dry ]]; then
  echo "충돌 없음. $CLAUDE_HOME 에 스킬 5개·역할 5개·지휘 파일 3개·공통규약을 연결할 수 있다."
  [[ "$legacy" != true ]] || echo "기존 orchestration 디렉터리 링크를 파일별 연결로 전환한다."
  exit 0
fi
if [[ "$MODE" == check && "$legacy" == true ]]; then
  bad "orchestration 디렉터리 링크의 개별 연결 전환이 필요하다. 설치를 다시 실행한다."
  exit 1
fi

# 예전 방식(디렉터리 통째 링크)에서 파일별 링크로 옮긴다.
# 디렉터리를 통째로 걸면 나중에 저장소에 추가되는 파일이 소리 없이 함께 노출된다.
migrate_orch() {
  local dest="$CLAUDE_HOME/orchestration"
  [[ -L "$dest" && "$(readlink "$dest")" == "$REPO/shared/orchestration" ]] || return 0
  case "$MODE" in
    install|uninstall) rm "$dest"; skip "orchestration/ 디렉터리 링크를 파일별 링크로 교체" ;;
    *) skip "orchestration/ 이 아직 디렉터리 링크다 — 설치를 다시 실행하면 파일별로 바뀐다" ;;
  esac
}
migrate_orch

[[ "$MODE" == "install" ]] && mkdir -p "$CLAUDE_HOME/skills" "$CLAUDE_HOME/agents" \
  "$CLAUDE_HOME/instructions" "$CLAUDE_HOME/orchestration"

act() { if [[ "$MODE" == "uninstall" ]]; then unlink_one "$@"; else link_one "$@"; fi; }

echo "저장소: $REPO"
echo "대상:   $CLAUDE_HOME"
echo
echo "스킬 (절차)"
for s in "${SKILLS[@]}"; do act "$REPO/shared/skills/$s" "$CLAUDE_HOME/skills/$s" "skills/$s"; done

echo "에이전트 (역할)"
for a in "${AGENTS[@]}"; do act "$REPO/claude/agents/$a.md" "$CLAUDE_HOME/agents/$a.md" "agents/$a.md"; done

echo "오케스트레이션 (지휘)"
for o in "${ORCH[@]}"; do act "$REPO/shared/orchestration/$o" "$CLAUDE_HOME/orchestration/$o" "orchestration/$o"; done
if [[ "$MODE" == "uninstall" ]]; then rmdir "$CLAUDE_HOME/orchestration" 2>/dev/null || true; fi

echo "공유 규약"
act "$REPO/shared/instructions/교재-공통규약.md" "$CLAUDE_HOME/instructions/교재-공통규약.md" "instructions/교재-공통규약.md"

echo
if [[ $problems -gt 0 ]]; then
  echo "문제 ${problems}건. 위 항목을 확인한다."
  [[ "$MODE" == "check" ]] && echo "설치하려면: bash scripts/install-claude.sh"
  exit 1
fi
case "$MODE" in
  check)     echo "전부 연결돼 있다." ;;
  dry)       echo "실제로 설치하려면 --dry-run 없이 실행한다." ;;
  uninstall) echo "제거 완료. 저장소의 원본은 그대로다." ;;
  install)   echo "설치 완료. 새 Claude Code 세션에서 /교재 로 시작한다." ;;
esac
