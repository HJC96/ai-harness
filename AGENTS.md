# AI Harness

이 저장소의 Codex 진입 지침은 [codex/AGENTS.md](codex/AGENTS.md)다. 작업 전에 읽는다.

- 사용자가 목차를 학습용 책으로 집필·개정해 달라고 요청하면 메인 세션은 오케스트레이터를 맡는다. 실제 집필은 역할별 서브에이전트에 위임한다.
- 이미 역할과 작업을 배정받은 서브에이전트는 리더가 되지 않고 자신의 작업 범위를 따른다.
- 하네스 코드·설정·문서 자체를 수정하는 요청은 유지보수 작업이다. 책 집필 파이프라인을 시작하지 않는다.
- 원본은 `codex/agents/`, `shared/skills/`에 있다. `.codex/agents/`, `.agents/skills/`는 검색용 연결 경로다.
- 검증: `python3 scripts/doctor.py`. 연결 복구: `bash scripts/install-codex.sh`.
