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
| 세션 | JWT. **access 30분 / refresh 7일** ※ 설계 원안 14일에서 단축 (아래) |
| refresh 저장 | 웹: `httpOnly` + `Secure` + `SameSite=Strict` 쿠키 / RN 앱: OS 보안저장소 (Keychain·Keystore) |
| 로그인 시도 제한 | 계정당 5회 실패 → 15분 잠금. IP 기준 rate limit 병행 |
| 비밀번호 정책 | 최소 12자. 복잡도 강제보다 **길이 + 유출 목록 대조**가 효과적 |

> ⚠️ JWT를 `localStorage`에 넣지 않는다 — XSS 한 방에 토큰이 털린다.

#### 구현 상태 (3단계 · SR15-1 해소, 2026-07-25)

한때 구현이 이 표를 어겼다 — 로그인 응답 본문으로 refresh 를 주고 프론트가 `localStorage` 에
저장했다(보안리뷰 SR-015 **FAIL**). **설계를 고치지 않고 구현을 설계에 맞췄다.**

| 항목 | 구현 |
|---|---|
| refresh 발급 | `POST /auth/login` 이 **쿠키로만** 심는다 — `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth; Max-Age=604800`. **응답 본문에 refresh 필드가 없다** |
| refresh 사용 | `POST /auth/refresh` 는 **요청 본문을 받지 않는다.** 쿠키로만 인증하고, 매번 **새 쿠키로 회전**시킨다 |
| 실패 처리 | 쿠키 없음·만료·서명오류·종류불일치 → 401 + 쿠키 즉시 삭제(`Max-Age=0`). 사유는 구분해 알려주지 않는다 |
| 로그아웃 | `POST /auth/logout` → 204 + 쿠키 삭제(발급과 **동일한** 이름·Path·속성) |
| access 저장 | 클라이언트 **메모리 전용**. 새로고침 시 쿠키로 조용히 재발급 |
| 토큰 종류 | `typ` 클레임을 양방향 검증 — refresh 로 API 호출 불가, access 를 refresh 쿠키에 심어도 불가 |
| `Secure` 분기 | `COOKIE_SECURE` 설정. **`DEBUG=false` 면 설정과 무관하게 항상 `Secure`** (`Settings.refresh_cookie_secure`) — 로컬 http 개발에서만 끌 수 있다 |

**CSRF** — 쿠키를 쓰는 순간 CSRF 가 성립할 여지가 생긴다. 두 겹으로 막는다.
1. `SameSite=Strict` — 다른 사이트에서 출발한 요청에는 브라우저가 쿠키를 붙이지 않는다.
2. `X-Requested-With: XMLHttpRequest` 커스텀 헤더를 `/auth/refresh`·`/auth/logout` 이 **요구**한다.
   HTML `<form>` 은 커스텀 헤더를 붙일 수 없고, 스크립트로 붙이면 CORS 사전요청에 걸린다.
   없으면 `403 CSRF_HEADER_REQUIRED`. ⚠️ 이때 **쿠키를 지우지 않는다** — 지우면 헤더 없는
   요청을 반복시켜 남의 세션을 끊는 로그아웃 CSRF 가 된다.

**refresh TTL 14일 → 7일.** 쿠키+회전으로 탈취 난이도는 올라갔지만 **서버측 폐기 수단이 아직
없다**(아래 SR15-3). 회수할 방법이 없는 동안은 노출 창을 시간으로 줄이는 것이 유일한 통제다.
denylist 를 붙이기 전에는 이 값을 다시 늘리지 않는다.

**후속 과제 SR15-3 (미구현 · 비차단)** — 서버측 토큰 폐기. 지금 `/auth/logout` 은 **브라우저에서
지우는 것까지**가 전부이고, 이미 발급된 refresh 는 만료(7일)까지 서버가 유효하다고 본다.
토큰에 `jti` 클레임은 이미 넣어 뒀으므로(`core/security.py`), 폐기 목록(Redis 또는 테이블) +
로그아웃·비밀번호 변경 시 등록만 붙이면 된다. 그때까지의 잔여 위험은 §8 `R-09`.

**SR15-4 (해소 · 2026-07-26)** — 프론트 CSP. `deploy/nginx-realestate.conf` 에
`Content-Security-Policy` 를 **보안헤더 5종의 하나로** 넣었다(server · 정적자산 ·
`/index.html` 세 블록 모두 — `add_header` 는 상속되지 않는다).

HttpOnly 쿠키(SR15-1)는 토큰의 **반출**만 막는다. XSS 가 그 탭 안에서
`fetch('/api/...', {credentials:'include'})` 를 부르거나 `/auth/refresh` 를 직접 때리는
**세션 라이딩**은 못 막는다 — CSP 가 그 마지막 층이다.

```
default-src 'self'; script-src 'self' https://dapi.kakao.com https://t1.daumcdn.net;
style-src 'self' 'unsafe-inline'; img-src 'self' https://t1.daumcdn.net
https://mts.daumcdn.net https://s1.daumcdn.net; connect-src 'self'; font-src 'self';
object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'
```

출처는 **카카오맵 SDK v4.5.13 을 실제로 내려받아 URL 생성부를 읽고** 정했다.
설계 단계에 적어 뒀던 `https://*.daumcdn.net` 와일드카드는 쓰지 않는다 — 실제로 필요한
호스트는 `t1`(스크립트·마커) · `mts`(타일) · `s1`(빈 타일) 셋뿐이다.
`style-src 'unsafe-inline'` 은 SDK 가 지도 판 배치에 `style.cssText` 와
`setAttribute("style", ...)` 를 쓰기 때문에 불가피하다(script-src 는 그대로 조여 둔다).

- 값은 `map $host $re_csp` 로 **한 곳에서만** 정의한다(세 블록의 값이 갈라질 수 없다).
- 배포는 **Report-Only → 확인 → 강제** 순서다(DEPLOY.md §5-5(3)~(5)).
- 누락 방지: DEPLOY.md §5-6 `check_headers()` 가 4경로에서 실검증하고,
  `backend/tests/test_deploy_config.py` 가 커밋 시점에 정적으로 막는다.

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

> ### ⚠️ **검증 실패 응답도 노출 경로다** (3단계에서 발견 · SR-025)
> 이 절은 오랫동안 **로그만** 말했다. 그런데 실제로 민감정보가 되돌아온 자리는
> 로그가 아니라 **422 응답 본문**이었다: FastAPI 기본 검증 핸들러가 오류마다
> `input`(사용자가 보낸 원본 값)을 실어서, `POST /auth/register` 의 비밀번호가
> 12자 미만이면 **평문 비밀번호가 응답으로 그대로 돌아왔다**(실측).
> 자산 금액(`/me/profile`)도 같았다. 보낸 사람에게 돌려주는 것이라 '유출'은 아니지만,
> 그 값이 브라우저 콘솔·프론트 오류 리포팅·프록시 캐시에 남을 자리가 너무 많다.
>
> 그래서 규칙을 하나 더 둔다 — **에러 응답은 사용자가 보낸 값을 되돌려 주지 않는다.**
> - `RequestValidationError` 핸들러는 `type`·`loc`·`msg` 만 남긴다(`input` 제거).
>   (덤으로 `Infinity`·`NaN` 이 `input` 에 실려 422 가 500 으로 바뀌던 문제도 닫힌다.)
> - `msg` 도 안전하지 않다 — **커스텀 검증기**가 `ValueError(f"…{값}")` 로 값을
>   문장에 넣으면 그대로 되돌아간다. 검증기는 **값 대신 위치(`loc`·index)로 지목**하고,
>   핸들러는 `msg` 길이에 상한(200자)을 둔다(SR25-2).

> ### ⛔ **URL 은 네 번째 로그다** (3단계에서 발견 · SR32-1 · CWE-532)
> 위 규칙은 **본문**을 지켰다. 그런데 정작 새 나간 것은 본문이 아니라 **쿼리스트링**이었다:
>
> ```
> GET /api/v1/map/complexes?bbox=…&max_price_krw=1314310000
>                                  └ /affordability 가 암호문을 복호화해 계산한 최대 구매가능액
> ```
>
> 운영 nginx 로그에 **148줄**, 그중 101줄이 **0644(월드 리더블)** 이었고 같은 호스트의
> 다른 서비스 계정으로 실제로 읽혔다. `SENSITIVE_FIELDS` 도, "본문 로그 금지"도 이 값을
> 막지 못했다 — **이름이 `cash`·`income` 이 아니었고, 본문이 아니었기 때문이다.**
>
> 그래서 규칙을 세 줄 더한다.
> 1. **개인·민감정보와 그 파생값을 URL 파라미터·쿼리스트링에 넣지 않는다.**
>    파생값이 더 위험하다 — 원본이 아니라서 눈에 안 띄는데, 한도는 자산의 단조 함수라
>    몇 건만 모여도 원본이 좁혀진다. 필요하면 **본문(POST)** 으로 보내거나,
>    **인증된 경로에서는 아예 보내지 않고 서버가 저장된 프로필로 만든다**
>    (`GET /map/complexes?budget=mine` — api-spec.md §4).
> 2. **접근 로그의 쿼리 값은 기본이 '지운다'** 이다. 예전에는 민감 경로 목록
>    (`SENSITIVE_PATHS`)에 실린 경로만 지웠는데, 목록은 새 엔드포인트가 생길 때마다
>    사람이 기억해야 하고 **기억은 언젠가 빠진다**(이 사고가 바로 그것이다).
>    지금은 경로와 **파라미터 이름만** 남긴다(`/map/complexes [q: bbox,budget,zoom]`).
> 3. **싱크는 하나가 아니다.** 앱 미들웨어가 지운 줄을 uvicorn 이 한 줄 아래에 다시 쓰고,
>    nginx 가 또 쓴다. 셋 다 막아야 막힌 것이다:
>    ① 앱 미들웨어(`main.log_target`) ② `uvicorn.access` 필터
>    (`masking.install_access_log_query_stripping`, `install_log_masking` 이 함께 건다)
>    ③ nginx 전용 `log_format re_noquery`(`$request` 금지 · `$uri` 사용, **이 사이트 블록에만**).

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
- [ ] **자산 금액과 그 파생값(`max_purchase_krw` 등)이 URL 쿼리에 실리는 곳이 없는가**
      — GET 라우트의 쿼리 파라미터를 **전수로** 훑는다(SR32-1). 파생값은 이름에
      `cash`·`income` 이 없어 눈에 띄지 않는다. 회귀 그물:
      `backend/tests/test_api.py::test_모든_GET_쿼리_값은_로그에_남지_않는다`(앱 라우터를
      순회해 카나리를 심는다 — ⚠️ SR33-5: 예전에 이 줄이 `test_access_log.py` 를 가리켰다.
      문장과 코드가 어긋나면 다음 사람은 코드가 아니라 문장을 믿는다) ·
      프론트 `src/test/urlPrivacy.test.tsx`
- [ ] **접근 로그 세 싱크(앱·uvicorn·nginx)가 모두 쿼리를 지우는가**
      — 하나만 막으면 나머지가 계속 쓴다. 코드 확인으로 끝내지 말고 **실제로 띄워서**
      로그를 읽는다(`backend/tests/test_access_log.py::test_실제_uvicorn_접근로그에_…`).
      ⚠️ 앱 계층은 **운영에서 INFO 가 출력되지 않는다**(root 핸들러 0개 · `lastResort`
      임계 WARNING — SR33-3). 실제로 도는 싱크는 uvicorn·nginx 둘이고, 앱 로거에서
      나가는 줄은 500 핸들러의 ERROR 다 → 그 줄도 `log_target` 을 쓴다(SR33-1,
      회귀 그물 `test_api.py::test_500_이_나도_쿼리_값은_로그에_남지_않는다`)
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
| R-09 | **서버측 토큰 폐기 수단 없음** — 유출된 refresh 를 만료 전에 회수할 수 없다 (SR15-3) | **이월**. 완화: refresh 를 `httpOnly` 쿠키로만 취급 + 호출마다 회전 + TTL 7일. 재평가 트리거: ① 사용자가 나 외로 늘어날 때 ② 세션 유지 요구로 TTL 을 늘리려 할 때 → 그 전에 `jti` denylist 를 붙인다 |

> R-06은 정직하게 말해 **완전한 방어가 아니다.** 서버가 통째로 털리면 키도 털린다.
> 다만 실무에서 훨씬 흔한 사고(DB 덤프 유출, 백업 파일 노출)는 확실히 막는다.
