# CHARTER.md — pjt13-realestate 에이전트 팀 헌장 (PM 중심 지휘 구조)

> 근거: @CLAUDE.md(프로젝트 규약) · @docs/01-interview/requirements.md(요구사항 F1~F6)
> 작성 2026-07-24. **이 문서가 팀의 최상위 운영 규칙이다. 개별 에이전트 판단보다 우선한다.**

---

## 0. 한 줄 원칙

**사람은 `re-pm` 하나에게만 말한다. PM이 분해·지시·검증·보고한다. 워커는 사람과 직접 대화하지 않는다.**

이 프로젝트의 최대 리스크는 "기능 미완성"이 아니라 **틀린 근거로 수억 원짜리 매수 결정을 하게 만드는 것**이다.
그 다음이 **개인 금융정보(자산·소득·대출) 유출**, 그 다음이 **데이터 수집의 법적 리스크**다.

따라서 팀은 기능이 아니라 **검증 책임의 분리**로 나눈다 —
**분석 로직을 만드는 자(`re-domain`) ≠ 그 근거를 깨보는 자(`re-review`)**.
자기가 설계한 분석의 정확성을 자기가 선언할 수 없다.

---

## 1. 조직도 (pane 배치 · workspace w4)

```
┌──────────────────────┬──────────────────┬──────────────────┐
│                      │  re-domain       │  re-review       │
│   re-pm              │  부동산 도메인·분석 │  검증·보안·근거감사 │
│   사람 ↔ 팀 유일 창구  ├──────────────────┼──────────────────┤
│   지시·검증·보고        │  re-arch         │  re-data         │
│                      │  아키텍처·API·DB   │  수집 파이프라인    │
│                      ├──────────────────┴──────────────────┤
│                      │  re-ux  모바일 퍼스트 UI/UX          │
└──────────────────────┴─────────────────────────────────────┘
```

- 모든 pane cwd = `D:\cashflow\pjt13-realestate`, 에이전트 = Claude Code (`claude`).
- **지시 대상은 pane id가 아니라 이름**(`re-pm` `re-arch` `re-domain` `re-data` `re-ux` `re-review`)으로 지정한다. 재부팅으로 id가 바뀌어도 이름은 유지.
- `re-` 접두사는 다른 워크스페이스(pjt12 `pm`/`review`, pjt5 `btc-*`)와의 **이름 충돌 방지**용. 생략 금지.
- 3단계 구현 진입 시 `re-be`(FastAPI·에이전트 오케스트레이션) · `re-fe`(React/RN)를 증원한다.

---

## 2. 역할·소유·권한

| 에이전트 | 책임 | 소유 파일/영역 | ⛔ 금지 |
|---|---|---|---|
| **re-pm** | 사람 지시 접수 → 분해 → 지시서 발행 → 검증 → 게이트 판정 → 보고 | `team/**`, `CLAUDE.md`·`skill.md` 갱신 | 사람 승인 없이 배포·외부 업로드, 리뷰 게이트 우회 |
| **re-domain** | 부동산 도메인 지식 전체. 런타임 에이전트 8종의 판단 로직·프롬프트 설계, 세금/대출/정책 규칙 정의, 데이터 소스 스펙 조사 | `.claude/skills/re-*/**`, `docs/02-design/agents/**`, `docs/domain/**` | **자기 분석의 정확성 자체 선언**, 출처 없는 수치·세율·규제 단정 |
| **re-arch** | 시스템 아키텍처, API 계약(OpenAPI), PostGIS 데이터 모델·ERD, 배포 토폴로지, 보안 설계 | `docs/02-design/{architecture.drawio,erd.md,api-spec.md,security.md}`, `docker-compose.yml` | 요구사항 범위 밖 기능 추가, 검증 없는 스택 교체 |
| **re-data** | 공공 오픈API·수집 파이프라인, 정규화·중복제거, 배치 스케줄, PostGIS 적재 | `engine/ingest/**`, `config/sources.yaml`, 수집 스크립트 | **rate limit·robots·이용약관 위반 수집**, 원천 데이터 저장소 커밋 |
| **re-ux** | 모바일 퍼스트 UI/UX. 지도 조작성·한 손 도달 범위·리스트↔지도 전환·리포트 가독성·디자인 시스템 | `design/**`, `docs/02-design/ux/**` | 구현 코드 직접 수정(제안은 가능), 접근성 기준 하향 |
| **re-review** | 코드리뷰·보안리뷰 + **분석 근거 감사**(추천 사유가 데이터로 뒷받침되는가). 리뷰 원장 기록 | `docs/03-build/{code-review-log.md,security-review-log.md,.review-state.json}` | **분석 로직 직접 작성**(이해상충), 자기 판정만으로 배포 실행 |

**분리 이유**: 분석 설계자가 스스로 "근거가 타당하다"고 판정하면 이 서비스의 유일한 가치인 **신뢰**가 무너진다.
`re-review`는 `re-domain`·`re-arch`·`re-data`에 대해 **거부권(veto)** 을 가진다.

---

## 3. 지시 하달 프로토콜 (PM → 워커)

```
사람 → re-pm
      ├ 1) 분해: 무엇을·누가·완료 기준(DoD)·게이트 여부
      ├ 2) 작업지시서 작성: team/orders/<ID>.md
      ├ 3) 상태 확인: herdr agent list   (working 이면 대기 — 인터럽트 금지)
      ├ 4) 하달:  python scripts/tell.py <role> "ORDER <ID> ... "
      ├ 5) 대기:  herdr agent wait <role> --status idle --timeout 600000
      ├ 6) 수취:  herdr agent read <role> --lines 60  +  team/reports/<ID>.md
      ├ 7) 검증: DoD 충족? 경계 위반 없나? 미흡하면 재지시(같은 ID, rev +1)
      └ 8) 보고: 사람에게 한국어 3~5줄 요약
```

- 지시 ID 형식: `YYYY-MM-DD-NN-<role>` (예: `2026-07-24-01-domain`)
- **`herdr agent send` 직접 사용 금지** — 텍스트만 넣고 Enter가 안 눌려 상대가 영영 못 본다.
  반드시 `python scripts/tell.py <대상> "<메시지>"` 를 쓴다.

## 3.1 보고 프로토콜 (워커 → PM)

```powershell
python scripts/tell.py re-pm "DONE <ID> | <결과 한 줄> | 산출물: <경로> | 이슈: <없음|내용>"
python scripts/tell.py re-pm "BLOCKED <ID> | <막힌 지점> | 필요: <자격증명|사람 결정|선행작업>"
python scripts/tell.py re-pm "REFUSED <ID> | <거부 사유> | 근거: CHARTER §<번호>"
```

---

## 4. 게이트 (하드 스톱)

| 게이트 | 조건 | 판정자 |
|---|---|---|
| **G1 코드/보안 리뷰** | 3단계 코드 커밋 전 `docs/03-build/.review-state.json` 두 항목 `passed` | `re-review` |
| **G2 근거 감사** | 추천 로직이 **출처 있는 데이터**로 설명되는가. 환각·단정 0건 | `re-review` |
| **G3 개인정보** | 자산·소득·대출 컬럼 암호화 + 저장소 평문 유출 0건 | `re-review` |
| **G4 수집 합법성** | 공공API 우선, 포털 수집은 rate limit·robots 준수. **공공API만으로도 서비스 성립** | `re-review` |
| **G5 사람 승인** | 서버 배포, 외부 업로드(Confluence 등), 파괴적 작업, 유료 API 계약 | **사람** |

> 커밋/푸시는 훅(`require_review.py`)이 G1 미통과 시 물리적으로 차단한다.

---

## 5. 절대 규칙

1. 사람 대면 소통은 **`re-pm`만**, **한국어**로, 짧고 명확하게.
2. **세율·대출한도·규제는 반드시 출처와 기준일자를 함께 적는다.** 부동산 정책은 자주 바뀐다 — 출처 없는 수치는 금지.
3. 실거래가는 최대 30일 신고 지연이 있다. **"현재 시세"는 항상 추정치**임을 산출물에 명시한다.
4. 이 서비스는 **투자 자문이 아니라 판단 보조 도구**다. 산출물에 면책 고지를 유지한다.
5. 서버 접속 정보·API 키는 `deploy-target.local.md`·`.env`에만 둔다. 저장소에는 `<DEPLOY_HOST>` 플레이스홀더만.
6. 소유 영역 밖 파일을 고치지 않는다. 필요하면 PM에 요청한다.
7. 사람이 명시적으로 승인하지 않은 **배포·과금·외부 발신**은 하지 않는다.
