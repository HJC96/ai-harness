# AI Harness

Codex와 Claude Code에서 함께 사용할 개인용 하네스 저장소입니다.

현재는 기본 디렉터리만 준비되어 있습니다. 반복해서 사용하는 작업 방식이 생기면
공통 지침, 스킬, 에이전트 정의를 작은 단위로 추가합니다.

## 구조

```text
shared/
  instructions/  여러 도구에서 공유할 지침 원본
  skills/         공통으로 관리할 스킬
codex/
  AGENTS.md       Codex용 지침
  agents/         Codex용 커스텀 에이전트
claude/
  CLAUDE.md       Claude Code용 지침
  agents/         Claude Code용 서브에이전트
scripts/          설치 및 점검 스크립트
```

## 운영 원칙

- 항상 적용할 짧은 규칙은 도구별 지침 파일에 둡니다.
- 재사용할 절차가 실제로 생겼을 때만 `shared/skills/`에 추가합니다.
- 에이전트 정의는 역할이 명확해진 뒤 각 도구의 디렉터리에 추가합니다.
- 인증 정보와 개인 환경의 실제 설정 파일은 커밋하지 않습니다.
