# Claude Code 하네스 — 목차로 만드는 학습 교재

목차 한 벌을 받아 **책처럼 이어 읽히는 학습용 Markdown 교재**를 만드는 Claude Code 하네스다. 메인 세션이 지휘를 맡고, 설계 · 집필 · 검수 · 엮기를 역할별 서브에이전트에 위임한다.

Codex 쪽 구현은 `codex/agents/`와 `shared/skills/book-*`에 따로 있다. 이쪽(Claude)은 `claude/agents/`와 `shared/skills/`의 `교재*`·`챕터*` 스킬을 쓴다.

## 설치

```bash
bash scripts/install-claude.sh            # ~/.claude 로 심볼릭 링크
bash scripts/install-claude.sh --check     # 상태 확인
bash scripts/install-claude.sh --uninstall # 이 하네스가 만든 링크만 제거
bash scripts/install-claude.sh --doctor    # 이름·참조 경로 정합성 점검
python3 -m unittest discover -s tests -v  # 임시 환경에서 설치·게이트·합본 회귀 검증
```

원본은 저장소에 남고 `~/.claude`에는 역할·지휘 파일별, 스킬별 링크가 생긴다. **저장소 파일을 고치면 다음 세션에 반영된다.** 설치 전에 전체 대상의 충돌을 확인하므로 뒤쪽 파일이 충돌해도 일부만 설치되지 않는다. 실제 파일과 다른 링크는 보존한다. `--doctor`는 설치 전에도 원본을 검사하고, `--check`는 설치된 링크를 검사한다. Python 3.8 이상이 필요하다.

사용자 지정 설정 디렉터리는 `CLAUDE_CONFIG_DIR=/절대/경로 bash scripts/install-claude.sh`로 지정한다. 이전 스크립트의 `CLAUDE_HOME`도 대체 변수로 받는다. 문서의 `~/.claude`는 기본 경로 표기이며 작업 배정에는 실제 설정 경로를 쓴다. 전역 `CLAUDE.md`나 권한 설정은 수정하지 않는다. 저장소에서의 진입 지침은 루트 `CLAUDE.md`가 이 문서를 불러온다.

설치 후 새 세션에서:

```text
/교재 <목차를 붙여넣거나 파일 경로>
/교재 이어서 ./jvm-memory
/교재 상태 ./jvm-memory
```

## 세 레이어

| 레이어 | 대답하는 질문 | 파일 | 담지 않는 것 |
|---|---|---|---|
| **오케스트레이션** | 누가 · 언제 · 누구와 · 무엇을 | `shared/orchestration/` | 역할의 판단 기준, 작업 절차 |
| **에이전트** | 누가 맡고 무엇으로 판단하는가 | `claude/agents/*.md` | 절차, 팀 구성 |
| **스킬** | 어떤 순서로 하는가 | `shared/skills/`의 한글 스킬 5개 | 팀 배치, Phase 전환 |

여기에 하나 더 — **공유 규약**(`shared/instructions/교재-공통규약.md`)은 문체 · 형광펜 · 코드 예시처럼 여러 스킬이 같이 보는 기준이다. 절차가 아니라 기준이므로 스킬에 복사하지 않고 참조한다.

```text
shared/orchestration/
  교재-파이프라인.md      지휘자 규칙 · 팀 구성 · Phase 0~5 · 병렬 · 되돌림 · 재개
  산출물-계약.md          Phase 사이를 건너는 물건의 규격 (계약서 · 챕터 · 리포트 · 배정 메시지)
  book.py                 계약을 기계로 검증하는 도구 (게이트) · 합본 생성
claude/agents/
  curriculum-architect.md  목차 → 학습 경로와 챕터 계약
  chapter-writer.md        계약 1장 → 본문 1장
  technical-reviewer.md    정확성 축 검수
  learner-advocate.md      독자 축 검수
  learning-editor.md       낱장을 한 권으로
shared/skills/
  교재/           진입점. 접수 후 파이프라인에 넘긴다
  교재-설계/      Phase 1 절차
  챕터-집필/      Phase 2 절차 (재집필 포함)
  챕터-검수/      Phase 3 절차 (정확성 · 독자 두 모드)
  교재-엮기/      Phase 4 절차
shared/instructions/
  교재-공통규약.md 독자 · 문체 · 용어 · 코드 · 도식 · 형광펜
```

## 피하려는 안티패턴과 방지 장치

| 안티패턴 | 이 하네스에서 |
|---|---|
| **에이전트 한 명이 모든 역할을 맡는다** | 다섯으로 쪼갰다. 쓴 사람이 검수하지 않고(`chapter-writer` ≠ 검수자), 정확성과 독자 관점을 한 명에게 몰지 않는다(`technical-reviewer` ≠ `learner-advocate`). 각 에이전트 파일에 "내 축이 아닌 것"을 명시해 역할 침범을 막는다 |
| **스킬이 팀 전체를 지휘한다** | 진입점 `교재` 스킬은 입력 접수와 모드 판별까지만 하고 파이프라인 파일로 넘긴 뒤 끝난다. 나머지 스킬 어디에도 다른 에이전트를 부르는 절차가 없다 |
| **리더가 일을 직접 처리한다** | 지휘자는 배정·게이트·상태·보고를 맡는다. 계약 수정은 설계자, 본문 수정은 집필자, 판정은 독립 검수자에게 돌린다 |
| **에이전트 파일에 절차 지식을 다 넣는다** | 역할의 `skills` 메타데이터로 별도 스킬을 미리 불러온다. 역할 파일에는 책임·판단 기준·협업 경계를 두고 상세 점검 절차는 스킬에서 유지한다 |

## 기계가 보는 것과 사람이 보는 것

판단은 에이전트가, **확인은 스크립트가** 한다. 사람이 눈으로 세는 규칙은 반드시 새고, 특히 낡은 검수 판정은 눈으로 절대 못 잡는다.

```bash
python3 ~/.claude/orchestration/book.py check <출력경로> --stage plan
python3 ~/.claude/orchestration/book.py check <출력경로> --stage draft --chapter 03
python3 ~/.claude/orchestration/book.py check <출력경로> --stage review
python3 ~/.claude/orchestration/book.py check <출력경로> --stage final  # 기본값
python3 ~/.claude/orchestration/book.py inputs <출력경로> 03  # 집필 입력해시
python3 ~/.claude/orchestration/book.py review-inputs <출력경로> 03  # 검수 입력해시
python3 ~/.claude/orchestration/book.py build <출력경로>   # final 통과 후 합본
python3 ~/.claude/orchestration/book.py hash <파일>       # 원고·계약 판본 해시
```

`check`는 누락된 원고·검수, 미해결 S1, 리포트 대상·계약·원고 해시, 지적 개수 불일치, 중복 챕터 번호, 목차 누락과 의존성 순환을 확인한다. 계약·설계·선수 요약이 바뀌면 입력해시로 낡은 원고를 잡는다. S2/S3와 형광펜 개수 초과는 경고이며 S2만으로 편집을 막지 않는다. 최종 인계에서는 전체 챕터를 연결한 `index.md`와 확인 필요 주석의 해소도 요구한다.

챕터를 재집필하면 옛 리포트의 `S1: 0`이 그대로 남는다. 그래서 검수자는 판정에 **대상 원고의 해시**를 적고, 엮기 전에 대조한다. 판정은 챕터가 아니라 **판본**에 대한 것이다.

편집한 원고도 다시 두 축에서 독립 검수한다. 작업 상태는 `.교재상태.json`에서만 바꾸며, 검수 후 원고 메타데이터를 수정해 해시를 깨뜨리지 않는다. 합본에는 장별 앵커를 만들고 상대 경로를 보정하며, 원본과 기존 사용자 파일을 덮어쓰지 않는다.

기존 산출물에는 새 `입력해시`·`계약해시`·`검수입력해시`가 없으므로 게이트가 실패한다. 집필자가 입력 변경 영향을 확인하고 검수자가 현재 판본을 다시 검수한 뒤 채운다. 지휘자가 해시만 추가해 이전 판정을 통과시키지 않는다.

## 하네스를 고칠 때

새로 알게 된 것을 어디에 넣을지는 **무엇이 바뀌었는가**로 정한다.

| 바뀐 것 | 넣을 곳 |
|---|---|
| 누가 맡는가, 무엇을 근거로 판단하는가 | `claude/agents/<역할>.md` |
| 어떤 순서로 하는가, 무엇을 점검하는가 | `shared/skills/<스킬>/SKILL.md` |
| 언제 누구를 붙이는가, 언제 되돌리는가 | `shared/orchestration/교재-파이프라인.md` |
| 단계 사이에 무엇을 넘기는가 | `shared/orchestration/산출물-계약.md` |
| 어떤 문체로 쓰는가, 형광펜을 어떻게 칠하는가 | `shared/instructions/교재-공통규약.md` |
| 기계로 확인할 수 있는 규칙이 생겼다 | `shared/orchestration/book.py` — 점검표에 한 줄 더 쓰지 말고 스크립트에 넣는다 |

**규격을 바꿀 때는 계약을 먼저 고치고 스킬을 나중에 고친다.** 순서가 뒤집히면 스킬끼리만 아는 규격이 생기고, 그때부터 계약은 문서로만 남는다.

새 역할을 추가하기 전에 한 번 묻는다 — **기존 역할의 판단 기준이 흐려서 생긴 문제인가, 정말 새로운 축인가.** 판단 축이 겹치는 역할을 늘리면 검수 리포트가 서로를 베끼기 시작한다.

## 알아 둘 것

- 서브에이전트의 결과는 사용자에게 자동으로 보이지 않는다. 지휘자가 옮겨 적는다
- 모든 역할을 합쳐 작업자는 최대 3명이다. 이 한도와 파일 소유권은 지휘자가 따르는 협업 규칙이며 OS 수준의 접근 통제가 아니다
- 하네스 자체를 고치는 요청은 유지보수다. 집필 파이프라인을 시작하지 않는다
- 내부 작업 스킬은 `user-invocable: false`로 메뉴에서 숨기고 역할별로 미리 불러온다. 사용자 진입점은 `/교재`다. 설정 형식은 Claude Code의 [서브에이전트](https://code.claude.com/docs/en/sub-agents#preload-skills-into-subagents)와 [스킬](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill) 공식 문서를 따른다
