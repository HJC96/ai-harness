# AI Harness — 목차로 만드는 학습서

사용자가 제공한 목차를 Markdown 학습서로 집필하는 하네스 저장소입니다. 메인 세션이 오케스트레이터를 맡고, 설계·집필·검토·편집을 역할별 서브에이전트에 위임합니다.

**Claude Code 구현과 Codex 구현은 별도입니다.** 하나의 계약으로 묶지 않으며 역할·스킬·산출물 형식이 각자 다릅니다. 공용 디렉터리 `shared/`에도 두 구현의 파일이 이름으로 나뉘어 있습니다.

| | Claude Code | Codex |
| --- | --- | --- |
| 안내 | [claude/CLAUDE.md](claude/CLAUDE.md) | [codex/AGENTS.md](codex/AGENTS.md) |
| 역할 | `claude/agents/*.md` 5개 | `codex/agents/*.toml` 5개 |
| 스킬 | `shared/skills/`의 `교재*`·`챕터*` | `shared/skills/book-*` |
| 오케스트레이션 | `shared/orchestration/` (파이프라인·산출물 계약·`book.py`) | `orchestration/` |
| 설치 | `bash scripts/install-claude.sh` | `bash scripts/install-codex.sh` |
| 점검 | `bash scripts/install-claude.sh --doctor` | `python3 scripts/doctor.py` |
| Python | 3.9 이상 | 3.11 이상 (`doctor.py`가 `tomllib` 사용) |

## Claude Code로 사용하기

```bash
cd /path/to/ai-harness
bash scripts/install-claude.sh            # ~/.claude 로 역할·스킬·지휘 파일별 심볼릭 링크
bash scripts/install-claude.sh --doctor    # 원본의 이름·참조 경로 정합성, 정의 중복
```

설치 후 **새 세션**에서 `/교재`로 시작합니다.

```text
/교재 <목차를 붙여넣거나 파일 경로>
/교재 이어서 ./jvm-memory
/교재 상태 ./jvm-memory
```

산출물은 `<출력경로>/` 아래에 `목차-원문.md`·`목차.md`·`00-설계/`·`chapters/`·`검수/`·`index.md`로 생기고, 진행 상태는 `.교재상태.json`에 둡니다. 단계 사이의 통과 조건은 `book.py check`가 기계로 확인합니다. 역할 구성, 게이트, 하네스를 고칠 때의 규칙은 [claude/CLAUDE.md](claude/CLAUDE.md)에 있습니다.

## Codex로 사용하기

저장소 루트에서 시작합니다. 별도의 API 서버나 전역 설치가 필요하지 않습니다.

```bash
cd /path/to/ai-harness
bash scripts/install-codex.sh
python3 scripts/doctor.py
codex
```

설치 스크립트는 이 저장소의 역할 디렉터리와 `codex/skills.list`에 등록한 스킬만 상대 심볼릭 링크로 연결합니다. 기존 파일·다른 연결이 있으면 보존하고 오류를 반환합니다. 이전 버전이 만든 스킬 전체 연결만 개별 연결로 전환하며 원본은 보존합니다. `doctor.py`는 `tomllib`을 쓰므로 Python 3.11 이상이 필요합니다.

Codex 앱에서는 이 저장소를 프로젝트로 열고 **새 세션**을 시작합니다. 프로젝트 설정을 신뢰할지 묻는 경우 본인이 확인한 이 저장소를 신뢰해야 프로젝트 설정이 적용됩니다. 역할을 인식하지 못하면 세션을 다시 시작하고 [Codex 지침](codex/AGENTS.md)의 대체 역할 전달 방법을 확인합니다. 서브에이전트 도구가 없는 실행 환경에서는 이 워크플로를 실행할 수 없습니다.

첫 요청 예시:

```text
아래 목차를 학습서 집필 흐름에 따라 책으로 만들어줘.
메인은 오케스트레이터를 맡고 역할별 서브에이전트를 사용해줘.
독자는 자바 문법을 아는 백엔드 입문자이고, 한국어로 설명해줘.
결과는 books/http-basics/book.md로 만들어줘.

1. HTTP 요청과 응답
2. 메서드와 상태 코드
3. 헤더와 본문
```

목차를 채팅에 붙여 넣거나 [요청 양식](templates/book/request.md)을 복사해 파일로 전달하면 됩니다. 분량·독자·참고 자료는 선택 사항입니다. 목차 삭제·재배열이 필요하거나 주제가 모호하면 관련 선택을 확인합니다.

중단 후에는 `books/<책 이름>`을 지정해 이어서 집필해 달라고 요청합니다. `state.md`와 최신 검토 기록을 바탕으로 재개합니다.

### 책임 분리 (Codex)

| 구분 | 정의하는 것 | 파일 |
| --- | --- | --- |
| 에이전트 | 역할, 산출물 소유권, 판단 기준, 협업 경계 | [codex/agents/](codex/agents/) |
| 스킬 | 배정된 작업의 입력·수행 절차·결과 기준 | [shared/skills/](shared/skills/) |
| 오케스트레이터 | 팀 구성, 작업 배정, 의존성, 단계 전환, 재작업 | [orchestration/](orchestration/) |

| 역할 | 맡는 일 | 스킬 |
| --- | --- | --- |
| 메인 세션 | 작업 조정·기록·사용자 소통 | 집필 스킬을 직접 수행하지 않음 |
| `book_planner` | 목차를 학습 목표와 장별 명세로 설계 | `book-plan` |
| `book_researcher` | 사실·출처·버전 확인 | `book-research` |
| `book_writer` | 배정된 장의 본문·예제·연습·해설 | `book-write` |
| `book_reviewer` | 설계·원고·통합본의 독립 검토 | `book-review` |
| `book_editor` | 검토된 장을 하나의 책으로 편집 | `book-edit` |

역할 파일에는 상세 절차를 넣지 않습니다. 스킬은 작업자 생성이나 단계 전환을 수행하지 않습니다. 리더는 원고를 직접 작성·보완하지 않고 문제를 담당자에게 돌려보냅니다. 저자와 검토자는 서로 다른 작업자이며 역할을 바꿔 겸하지 않습니다.

### 진행 흐름 (Codex)

```text
목차 입력 → 학습 설계 → 설계 검토
                       ↓
           장별 조사 → 집필 → 독립 검토
                       ↓ 모든 장 통과
               통합 편집 → 최종 검토 → book.md 전달
```

서로 독립적인 작업을 최대 3명까지 병렬 실행합니다. 선행 장이 필요한 원고는 그 장의 검토가 끝난 뒤 작성합니다. 자세한 통과 조건과 재작업 규칙은 [집필 흐름](orchestration/learning-book.md)에 있습니다.

오케스트레이션은 메인 Codex가 읽고 따르는 문서 규약입니다. 별도 프로그램이 단계를 강제로 실행하는 워크플로 엔진은 아닙니다. 파일 소유권도 협업 규칙이며 OS 수준의 파일별 접근 제한은 아닙니다. 모델과 권한은 현재 세션 설정을 상속합니다.

### 책의 산출물 (Codex)

```text
books/<책 이름>/
  request.md                   사용자 목차·요구 원문
  state.md                     진행 상태·작업 소유권·재개 정보
  plan.md                      목차 대응·학습 목표·장 의존성
  research/ch01.md             장별 조사 근거
  chapters/ch01.md             장별 원본
  reviews/<작업 ID>.md         독립 판정과 검토 파일 해시
  handoffs/<작업 ID>.md        담당자의 결과·미해결 사항
  book.md                      전체 본문이 들어 있는 최종 책
  README.md                    읽기 안내
```

내용이나 입력 자료가 변경되면 그 자료를 사용한 후행 작업의 검토까지 무효화됩니다. 핵심 사실이 확인되지 않았거나 검토 결함이 남아 있으면 완성본으로 표시하지 않습니다. 산출물은 로컬에 생성되며 커밋·푸시는 별도 요청으로 수행합니다.

## 저장소 구조

```text
CLAUDE.md                      Claude Code 진입점 (claude/CLAUDE.md를 불러온다)
claude/
  CLAUDE.md                    Claude Code 하네스 안내·유지보수 규칙
  agents/*.md                  역할 5개
shared/orchestration/          Claude: 파이프라인·산출물 계약·book.py
shared/skills/교재*, 챕터*      Claude: 절차 5개
shared/instructions/교재-공통규약.md   Claude: 문체·형광펜 등 공유 기준

AGENTS.md                      Codex 진입점
.codex/config.toml             Codex: 서브에이전트 활성화·동시 실행 한도
.codex/agents -> ../codex/agents
.agents/skills/book-*          Codex: 등록한 각 shared/skills/book-*로 연결
codex/
  AGENTS.md                    Codex 실행 규칙
  skills.list                  Codex에 연결할 스킬 목록
  agents/*.toml                역할 5개
orchestration/                 Codex: 리더의 책임·작업 의존성과 단계 전환
shared/skills/book-*           Codex: 절차 5개
shared/instructions/book-contract.md, project-guide.md   Codex: 공통 원칙·산출물 계약
templates/book/                Codex: 요청·진행 상태 양식
books/                         Codex: 책별 산출물

scripts/                       설치·정적 점검 (install-claude.sh, install-codex.sh, doctor.py)
tests/                         임시 환경에서 설치·게이트·합본 회귀 검증
docs/                          하네스 개선 계획
```

원본은 저장소에서 수정합니다. 설치 스크립트는 원본을 가리키는 링크만 만들고, 링크가 사라지면 다시 실행해 복구합니다.

## 점검과 근거

```bash
bash scripts/install-claude.sh --doctor    # Claude 원본 정합성
python3 scripts/doctor.py                  # Codex 연결·TOML·메타데이터·링크
python3 -m unittest discover -s tests -v   # 두 구현의 설치·게이트 회귀
git diff --check
```

두 점검 모두 파일 형식과 연결만 확인합니다. 실제 탐색 결과나 책의 교육적 품질을 보증하지 않으며, 최종 품질은 독립 검토 기록으로 확인합니다.

Codex 검색 위치와 파일 형식은 [커스텀 에이전트](https://learn.chatgpt.com/docs/agent-configuration/subagents), [스킬](https://learn.chatgpt.com/docs/build-skills), [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) 공식 문서를 기준으로 구성했습니다.
