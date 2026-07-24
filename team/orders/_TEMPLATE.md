---
id: YYYY-MM-DD-NN-<role>          # 예: 2026-07-24-01-domain
to: re-domain | re-arch | re-data | re-ux | re-review
rev: 1                            # 재지시 시 +1
gate: none | review-required | human-approval
status: dispatched
---

## 목적 (왜 하는가)
<한 문장. 어떤 요구사항(F1~F6)/게이트(G1~G5)를 움직이는지>

## 근거
<docs/01-interview/requirements.md §<번호> / 사람 요청 / 이전 보고 team/reports/<ID>.md>

## 작업
- [ ] <구체 작업 1>
- [ ] <구체 작업 2>

## 산출물 (정확한 경로)
- `<path>`

## 완료 기준 (DoD — 검증 가능하게)
- <이 문장이 참이면 완료. "잘 만든다"는 DoD 가 아니다>

## 경계 (하지 말 것)
- 소유 영역 밖 파일 수정 금지 (CHARTER §2)
- <이 작업 특유의 금지사항>

## 보고
```powershell
python scripts/tell.py re-pm "DONE <id> | 결과 | 산출물 | 이슈"
```
