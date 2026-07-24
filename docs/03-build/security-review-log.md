# security-review-log.md — 보안리뷰 원장

> 3단계 구현의 필수 게이트. 커밋/푸시 전 매 변경마다 기록한다.

---

## SR-001 · 2026-07-24 · 1단계 산출물 최초 커밋

**판정: PASS**

### 리뷰 범위
애플리케이션 코드는 아직 없음. 이번 변경은 **문서·설정 파일 전용**이며, 실질 위험은
**공개 GitHub 저장소(`wansoo88/realestate`, public)로의 비밀정보 유출**이므로 이에 집중해 점검함.

| 대상 | 파일 |
|---|---|
| 설정 | `.gitignore`, `.env.example` |
| 문서 | `CLAUDE.md`, `skill.md`, `docs/**` |

### 점검 항목 및 결과

| # | 항목 | 결과 | 근거 |
|---|---|---|---|
| S1 | 서버 IP·접속 계정 노출 | ✅ PASS | 실제 IP·SSH 키명·`root@` 문자열이 추적 대상 파일에 전무. `<DEPLOY_HOST>` 플레이스홀더로 치환됨 |
| S2 | 비밀정보 파일 제외 | ✅ PASS | `git check-ignore` 실검증 — `deploy-target.local.md`, `.env`, `*.key`, `id_rsa*`, `*.pem` 모두 IGNORED |
| S3 | 예외 규칙 오작동 | ✅ PASS | `.env.*` 무시 + `!.env.example` 예외가 의도대로 동작(예제 파일은 TRACKED) |
| S4 | 하드코딩된 크리덴셜 | ✅ PASS | `git diff --cached` 전수 스캔 결과 API 키·비밀번호·개인키 **값** 0건. 탐지된 3건은 `.env.example`의 빈 플레이스홀더 |
| S5 | 개인정보 커밋 | ✅ PASS | 자산·소득·대출 등 실제 개인 금융정보가 문서에 포함되지 않음 (요구사항 수준 서술만) |
| S6 | 보안 요구사항 문서화 | ✅ PASS | 컬럼 암호화·로그인 인증·HTTPS·SSH 하드닝이 `requirements.md`·`CLAUDE.md`에 명시됨 |

### 확인된 위험 (조치 예정 — 이번 커밋의 결격 사유 아님)

| ID | 위험 | 심각도 | 조치 시점 |
|---|---|---|---|
| R-01 | 배포 서버에 **root 계정 직접 SSH** 접속. 공인 IP 노출 서버는 상시 자동 공격 대상 | **High** | 2단계 `security-design` |
| R-02 | SSH 키를 타 프로젝트(autobtc)와 공용 사용 — 한쪽 유출 시 전파 | Medium | 2단계 `security-design` |
| R-03 | 포털 매물 수집의 이용약관 위반 소지 (법적 리스크) | Medium | 2단계 설계 시 공공API 이중화로 완화 |
| R-04 | 자산·소득 등 민감 컬럼 암호화 방식(pgcrypto vs 앱단 AES) 미확정 | Medium | 2단계 `db-modeling` + `security-design` |

> R-01·R-02의 구체 조치안은 `deploy-target.local.md`(저장소 밖 · git 제외)에 정리해 둠.

### 판정 사유
이번 변경에는 실행 코드가 없고, 공개 저장소 유출 벡터(S1~S5)가 모두 실측으로 차단 확인되어 **PASS**.
단, R-01~R-04는 2단계 보안설계에서 반드시 해소한다.

> ⚠️ 이 판정은 **문서 커밋 한정**이다. 3단계에서 실제 코드가 들어오면 OWASP Top 10 기준 정식 보안리뷰를 새로 수행하고, 그 전까지 이 PASS를 코드 변경의 근거로 재사용하지 않는다.
