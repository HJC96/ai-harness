# 학습용 책의 작업 계약

이 문서는 파일 형식과 인수인계 규약을 정의한다. 작업 순서는 `orchestration/learning-book.md`, 수행 절차는 해당 스킬을 따른다. `<book>`은 오케스트레이터가 정한 `books/<slug>` 절대 경로다.

## 산출물과 소유권

| 경로 | 작성자 | 내용 |
| --- | --- | --- |
| `<book>/request.md` | 오케스트레이터 | 사용자 요청·목차 원문, 추가 답변, 명시한 기본값 |
| `<book>/state.md` | 오케스트레이터 | 단계, 작업 배정, 의존성, 재검토 상태, 다음 행동 |
| `<book>/plan.md` | `book_planner` | 목차 대응표, 장 ID·파일명·선수 장, 학습 목표, 범위와 제외 주제의 소유 장 ID, 장 사이 이어받을 문장과 넘길 문제, 관통 사례와 장면 배분, 레벨 표, 용어 기준 |
| `<book>/research/<chapter-id>.md` | `book_researcher` | 장별 주장·근거·자료 접근 한계 |
| `<book>/chapters/<chapter-id>.md` | 해당 장의 `book_writer` | 설명·예제·연습·해설이 포함된 본문 |
| `<book>/reviews/<task-id>.md` | `book_reviewer` | 검토 대상과 판정, 근거가 있는 지적 사항 |
| `<book>/book.md` | `book_editor` | 목차와 모든 장을 포함한 최종 단일 Markdown 책 |
| `<book>/README.md` | `book_editor` | 독자 안내와 책·장 파일 링크 |
| `<book>/handoffs/<task-id>.md` | 해당 작업자 | 완료 내용, 파일, 미해결 사항 |

장 ID는 `ch01`, `ch02`처럼 책 안에서 고정한다. 작업 ID는 `plan-r1`, `research-ch01-r1`, `write-ch01-r1`, `review-ch01-fact-r1`, `review-ch01-reader-r1`, `edit-r1`, `review-final-r1`처럼 역할·범위·회차를 구분한다. 한 장을 두 축이 검토하므로 장 검토 ID에는 축을 넣는다. 축이 빠지면 두 검토자가 같은 `reviews` 파일을 소유하게 된다. 서로 다른 작업자가 같은 파일을 동시에 소유하지 않는다. 모든 결과물은 UTF-8 Markdown이다.

## 배정 메시지

작업자가 이전 대화를 보지 않아도 수행할 수 있게 다음 항목을 전달한다.

```text
task_id:
role: 역할 이름과 TOML 절대 경로
skill: SKILL.md 절대 경로
book_root:
goal: 이번 작업의 결과
inputs: 파일 절대 경로와 실제 SHA-256, 선행 작업 ID
owned_paths: 수정할 수 있는 파일의 정확한 목록
acceptance: 이번 산출물의 완료 조건
report_path: handoffs/<task-id>.md
```

배정 범위 밖의 결과물이 필요하면 `blocked` 또는 수정 요청으로 반환한다. 다른 작업자를 직접 호출하거나 다른 장까지 몰래 작성하지 않는다.

## 인수인계 문서

```markdown
# 작업 결과
- task_id:
- role:
- status: done | needs_revision | blocked
- inputs: 실제 사용한 모든 파일의 경로와 SHA-256, 선행 작업 ID
- outputs: 실제 작성한 파일 목록

## 확인한 내용
완료 조건에 대한 근거와 실제 실행한 검증을 적는다.

## 남은 문제
없으면 없음으로 적는다. 자료 접근 실패, 사실 불확실성, 요청 범위 변경을 명시한다.

## 다음 담당자에게
해결해야 하는 문제와 관련 위치만 전달한다. 직접 작업을 배정하지 않는다.
```

`done`은 배정된 산출물이 준비됐다는 뜻이다. 책 전체의 다음 단계 진행이나 출고 승인은 아니다. 최종 채팅에도 상태·파일 경로·미해결 사항을 짧게 반환한다.

## 검토 판정

검토 문서에는 `PASS`, `REVISE`, `BLOCKED` 중 하나의 판정, `검토 파일 경로 + SHA-256`, 검토에 사용한 request·plan·research·선행 원고 등 모든 입력의 경로·SHA-256을 기록한다. Python 표준 라이브러리 `hashlib` 또는 사용 가능한 해시 도구로 실제 파일 바이트의 해시를 계산한다. 해시를 추측하지 않는다. 배정 시의 해시와 실제 읽은 해시가 다르면 입력 변경으로 보고한다.

- `PASS`: 맡은 범위의 필수 조건 충족, 해결하지 않은 중대 결함 없음.
- `REVISE`: 오류, 목차 누락, 설명의 비약, 잘못된 해설 등 수정 가능한 결함 존재.
- `BLOCKED`: 근거·입력·도구가 없어 필수 검증을 마칠 수 없음.

각 지적은 ID, 심각도(`major`/`minor`), 파일·절, 이유, 필요한 수정, 재검토 결과를 포함한다. `major`가 열려 있으면 `PASS`를 주지 않는다. `minor`를 남길 때는 학습을 방해하지 않는 이유를 적는다. 본문 또는 사용한 입력이 변경되면 이전 `PASS`를 재사용할 수 없다.
