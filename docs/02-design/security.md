# 보안 설계 — 부동산 AI 자문 시스템

> 2단계 설계 산출물 · 2026-07-24 · 기준: OWASP Top 10 (2021) / ASVS L2
> 이 문서는 **3단계 `security-review` 게이트(G1·G3·G4)의 판정 기준**이 된다.
> 실제 서버 IP·계정·키 경로는 저장소 밖 `deploy-target.local.md` 참조.

---

## 0. 이 프로젝트의 보안 문제는 무엇인가

일반적인 웹앱과 다른 점 두 가지다.

1. **저장하는 개인정보가 유난히 민감하다.** 이름·이메일이 아니라 **보유현금·연소득·기존대출**이다.
   유출되면 금융사기·표적 범죄의 직접 재료가 된다. 사용자가 1명이라 "규모가 작으니 괜찮다"가 성립하지 않는다.
2. **공인 IP가 노출된 단일 서버**에서 돌아간다. 관리형 서비스의 기본 방어가 없다. 전부 직접 세워야 한다.

---

## 1. 보호 자산과 위협 모델

| 자산 | 민감도 | 주요 위협 | 대응 |
|---|---|---|---|
| 사용자 자산·소득·대출 | **최상** | DB 덤프 유출, 로그 노출, 백업 유출 | §3 앱단 암호화 + 로그 제외 |
| 로그인 자격증명 | 상 | 크리덴셜 스터핑, 해시 크랙 | Argon2id, rate limit |
| 서버 접근 권한 | **최상** | SSH 무차별 대입, root 탈취 | §4 하드닝 |
| API 키 (Claude·공공API·카카오) | 상 | 저장소 커밋, 과금 폭탄 | `.env` 전용, 커밋 차단 |
| 수집 데이터 | 중 | 무결성 훼손(잘못된 시세 = 잘못된 판단) | 출처·수집시각 기록, 이상치 탐지 |
| 추천 근거 | 중 | 환각·조작된 근거 | G2 근거 감사 (`re-review`) |

### 위협 시나리오 (구체적으로)
| ID | 시나리오 | 심각도 | 차단 지점 |
|---|---|---|---|
| T1 | 5432 포트 스캔 → PostgreSQL 직접 접속 → 자산 테이블 덤프 | **치명** | DB 포트 미개방 + 암호화 |
| T2 | SSH root 무차별 대입 성공 → 서버 전체 장악 | **치명** | root 로그인 차단 + 키 전용 |
| T3 | 서버 백업 파일이 웹 루트에 노출 → 평문 자산 유출 | 높음 | 암호화 + 웹 루트 밖 보관 |
| T4 | 에러 스택트레이스에 자산 금액 포함되어 로그 유출 | 높음 | 로그 필터 (§3.3) |
| T5 | 공개 GitHub 저장소에 `.env` 커밋 | 높음 | `.gitignore` + 커밋 전 스캔 |
| T6 | 다른 사용자의 `job_id` 추측 → 남의 추천 결과 조회 | 중 | 소유권 검증 (IDOR 방지) |
| T7 | Claude API 키 유출 → 과금 폭탄 | 중 | 키 분리, 사용량 알람 |

---

## 2. 인증 · 인가

### 2.1 인증
| 항목 | 결정 |
|---|---|
| 비밀번호 해시 | **Argon2id** (`bcrypt` 대비 GPU 공격 저항 우수). 파라미터는 서버 사양에 맞춰 튜닝 |
| 세션 | JWT. **access 30분 / refresh 14일** |
| refresh 저장 | 웹: `httpOnly` + `Secure` + `SameSite=Strict` 쿠키 / RN 앱: OS 보안저장소 (Keychain·Keystore) |
| 로그인 시도 제한 | 계정당 5회 실패 → 15분 잠금. IP 기준 rate limit 병행 |
| 비밀번호 정책 | 최소 12자. 복잡도 강제보다 **길이 + 유출 목록 대조**가 효과적 |

> ⚠️ JWT를 `localStorage`에 넣지 않는다 — XSS 한 방에 토큰이 털린다.

### 2.2 인가 (IDOR 방지 — T6)
**모든 사용자 자원 조회에 소유권 검증을 강제한다.**
```python
# 나쁜 예 — job_id 만으로 조회
job = db.get(RecommendationJob, job_id)

# 올바른 예 — 항상 user_id 를 조건에 포함
job = db.query(RecommendationJob).filter_by(id=job_id, user_id=current_user.id).one_or_none()
```
- `job_id`는 **ULID**(순차 추측 불가). 하지만 ID 추측 난이도에 의존하지 않는다 — 소유권 검증이 본질.
- 3단계 코드리뷰 필수 확인 항목.

---

## 3. 민감 데이터 보호

### 3.1 암호화 방식 결정 — `erd.md` Q1 해소

**결정: 앱단 AES-256-GCM (pgcrypto 아님)**

| 방식 | 장점 | 치명적 단점 |
|---|---|---|
| `pgcrypto` (`pgp_sym_encrypt`) | DB 안에서 완결 | **키가 SQL 문에 실려 전달**된다 → `pg_stat_activity`·쿼리 로그·slow query 로그에 키가 남을 수 있다. DB가 뚫리면 데이터와 키가 함께 털린다 |
| **앱단 AES-256-GCM** | 키가 앱 프로세스 메모리에만 존재. **DB 덤프가 유출돼도 복호화 불가**(T1·T3 차단) | DB에서 금액 검색·집계 불가 |

→ 단점(DB 내 검색 불가)이 **이 프로젝트에서는 문제가 되지 않는다.** 금액은 본인만 조회하고,
`/affordability` 계산은 애플리케이션이 복호화 후 수행한다. 금액으로 검색·정렬할 일이 없다.

```python
# 저장: AES-256-GCM, 레코드마다 랜덤 nonce
nonce = os.urandom(12)
ct = AESGCM(key).encrypt(nonce, str(amount).encode(), aad=f"user:{user_id}:cash".encode())
row.cash_krw_enc = nonce + ct     # bytea
```
- **AAD에 `user_id`+필드명을 묶는다** → 다른 사용자/필드로 암호문을 옮겨붙이는 공격 차단.
- 키: `FIELD_ENCRYPTION_KEY` (`.env`, 파일 권한 `600`). **저장소 커밋 금지.**
- 키 교체 절차를 3단계에서 마련(버전 프리픽스 `v1:` 부여).

### 3.2 전송 구간
- **HTTPS 강제.** HTTP → HTTPS 301. `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- Let's Encrypt + certbot 자동 갱신 (갱신 실패 알람 필수 — 만료되면 앱이 통째로 죽는다)
- TLS 1.2 이상만 허용

### 3.3 로그에서 민감정보 제외 (T4)
```python
SENSITIVE_FIELDS = {"cash_krw", "income_krw", "existing_loan_krw", "password",
                    "access_token", "refresh_token"}
```
- `/me/profile`, `/affordability`의 **요청·응답 본문을 접근 로그에서 제외**
- 예외 핸들러에서 스택트레이스의 로컬 변수 덤프 **비활성화**(프로덕션)
- 구조적 로깅 시 위 필드는 `***`로 마스킹

### 3.4 백업 (T3)
- `pg_dump` 결과물은 **암호화된 컬럼 상태 그대로** 저장됨 (앱단 암호화의 이점)
- 백업 파일은 **웹 루트 밖** + 권한 `600`
- **오프사이트 복사 필수** — 서버 안에만 두면 백업이 아니다
- 복구 훈련: 분기 1회 실제 복원 테스트 (안 해본 백업은 백업이 아니다)

---

## 4. 서버 하드닝 — SR-001의 R-01·R-02 해소

**현재 상태: `root`로 직접 SSH 접속 (High 위험).** 아래로 교체한다.

### 4.1 SSH
```bash
# 1) 배포 전용 계정
adduser --disabled-password deploy
usermod -aG docker,sudo deploy
mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
# 이 프로젝트 전용 키를 새로 발급해 등록 (autobtc 키 재사용 금지 — R-02)
```
```conf
# /etc/ssh/sshd_config
PermitRootLogin no              # R-01 해소
PasswordAuthentication no       # 키 전용
PubkeyAuthentication yes
AllowUsers deploy
Port 2222                       # 기본 포트 회피 (부수적 방어)
MaxAuthTries 3
ClientAliveInterval 300
```
> ⚠️ **적용 전 반드시 새 세션으로 접속을 검증**하고 기존 세션을 유지할 것. 잘못하면 서버에서 잠긴다.

### 4.2 방화벽
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 2222/tcp     # SSH
ufw allow 80,443/tcp   # 웹
ufw enable
# ⛔ 5432(PostgreSQL)·6379(Redis) 는 절대 개방하지 않는다 — T1
```
Docker Compose에서도 `db`·`redis`에 `ports:`를 **쓰지 않는다**
(Docker는 ufw를 우회해 포트를 열어버리므로, 방화벽만 믿으면 안 된다).

### 4.3 그 외
| 항목 | 조치 |
|---|---|
| 무차별 대입 | `fail2ban` (sshd + nginx) |
| 자동 보안 업데이트 | `unattended-upgrades` |
| 컨테이너 | 비 root 사용자로 실행, 읽기전용 파일시스템(가능한 곳) |
| nginx | 서버 토큰 숨김, 요청 크기 제한, `/api` rate limit |
| 키 관리 | 타 프로젝트와 공용 중인 기존 SSH 키 재사용 금지 → **이 프로젝트 전용 키 발급** (R-02). 키 파일명·경로는 `deploy-target.local.md` 참조 |

---

## 5. 데이터 수집 합법성 — R-03 해소 (G4)

| 규칙 | 강제 방법 |
|---|---|
| 공공 오픈API 1순위 | `config/sources.yaml`에 우선순위 명시, 포털은 보조로만 |
| **공공API만으로 서비스 성립** | 포털 소스 비활성화 상태로 E2E 테스트 통과 필수 (4단계) |
| `robots.txt` 준수 | 수집기가 robots를 파싱해 금지 경로는 요청 자체를 하지 않음 |
| rate limit | 요청 간 최소 간격 + 동시 요청 1, 지수 백오프 |
| User-Agent 명시 | 신원을 숨기지 않음 |
| 재배포 금지 | 수집 원천 데이터는 저장소 커밋 금지(`.gitignore: data/raw/`), 외부 제공 없음 |
| 판단 보류 | 애매하면 수집하지 않고 에스컬레이션 |

> 개인 비상업 용도 전제. 이 조건이 바뀌면(공개 서비스화·수익화) **수집 방식을 전면 재검토**해야 한다.

---

## 6. OWASP Top 10 (2021) 대응

| # | 항목 | 이 프로젝트에서의 위험 | 대응 |
|---|---|---|---|
| A01 | 접근통제 실패 | **T6 — 남의 추천 결과 조회** | 모든 쿼리에 `user_id` 조건 강제 (§2.2) |
| A02 | 암호화 실패 | 자산 평문 저장 | 앱단 AES-256-GCM (§3.1), HTTPS 강제 |
| A03 | 인젝션 | 지도 bbox·필터 파라미터 | ORM 파라미터 바인딩, **원시 SQL 문자열 조합 금지**. PostGIS 함수도 바인딩 |
| A04 | 안전하지 않은 설계 | 근거 없는 추천 = 설계 결함 | G2 근거 감사, `evidence` 필수 |
| A05 | 보안 설정 오류 | Docker 포트 노출, 디버그 모드 | `ports:` 미사용, `DEBUG=false` 강제 |
| A06 | 취약 컴포넌트 | 의존성 CVE | `pip-audit`/`npm audit` CI 편입 |
| A07 | 인증 실패 | 크리덴셜 스터핑 | Argon2id, 시도 제한, 긴 비밀번호 |
| A08 | 무결성 실패 | 잘못된 시세 적재 | 출처·수집시각 기록, 이상치 탐지, `ingest_log` |
| A09 | 로깅·모니터링 실패 | 수집 실패를 조용히 넘김 | `ingest_log` + 0건 연속 경보 (5단계) |
| A10 | SSRF | 정책 문서 URL 수집 | 허용 도메인 화이트리스트, 내부망 대역 차단 |

### LLM 특유 위험 (Top 10에 없지만 중요)
| 위험 | 대응 |
|---|---|
| **프롬프트 인젝션** — 수집한 매물 설명·정책 문서에 악의적 지시가 섞임 | 외부 텍스트는 **데이터로만** 전달(시스템 지시와 분리), 에이전트 출력은 스키마 검증 |
| **환각 근거** | 규칙 계산은 코드로, LLM은 설명만. `evidence` 없는 finding 반려 |
| **민감정보 외부 전송** | Claude API에 **자산 원본 금액을 그대로 보내지 않는다** — 계산 결과(한도·적합 여부)만 전달 |

> 마지막 항목은 설계에 반영해야 한다: `worker-agent`는 복호화된 금액을 프롬프트에 넣지 말고,
> 규칙 계산으로 도출한 `max_purchase_krw`·`적합/부적합` 판정만 넘긴다.

---

## 7. 3단계 security-review 체크리스트

커밋 전 `re-review`가 이 항목들을 확인한다. 하나라도 실패면 **FAIL**.

- [ ] `user_id` 조건 없는 사용자 자원 쿼리가 없는가
- [ ] 자산 3종이 암호화되어 저장되는가 (평문 컬럼 0개)
- [ ] `/me/profile`·`/affordability` 본문이 로그에서 제외되는가
- [ ] Claude API 프롬프트에 원본 금액이 포함되지 않는가
- [ ] 원시 SQL 문자열 조합이 없는가
- [ ] `docker-compose.yml`의 `db`·`redis`에 `ports:`가 없는가
- [ ] `.env`·키·백업 파일이 커밋되지 않았는가
- [ ] 세율·대출한도가 하드코딩 상수가 아니라 **출처·기준일자를 가진 설정**으로 관리되는가
- [ ] 수집기가 robots·rate limit을 준수하는가
- [ ] 포털 소스를 끄고도 서비스가 동작하는가

---

## 8. 잔여 위험 (수용 또는 이월)

| ID | 위험 | 상태 |
|---|---|---|
| R-05 | 단일 서버 — 침해 시 전면 노출 | **수용**(개인용). 백업 오프사이트로 완화 |
| R-06 | `FIELD_ENCRYPTION_KEY`가 같은 서버 `.env`에 존재 → 서버 장악 시 복호화 가능 | **수용**. DB만 유출되는 시나리오(T1·T3)는 차단됨. 향후 KMS 검토 |
| R-07 | 포털 수집의 약관 해석 여지 | 완화(공공API 이중화). 조건 변경 시 재검토 |
| R-08 | Claude API 응답의 환각 | G2 근거 감사로 완화. 완전 제거 불가 → **면책 고지 유지** |

> R-06은 정직하게 말해 **완전한 방어가 아니다.** 서버가 통째로 털리면 키도 털린다.
> 다만 실무에서 훨씬 흔한 사고(DB 덤프 유출, 백업 파일 노출)는 확실히 막는다.
