# 부동산 AI 자문 시스템

수도권 아파트를 대상으로, **내 자산·소득·선호 조건을 넣으면
"어느 단지 · 어느 타입을 · 왜" 사야 하는지 근거와 함께** 알려주는 개인용 웹 애플리케이션.

지도에서 매물을 보고, 전문가 에이전트들이 자금·시세·입지를 분석해 **순위와 사유**를 만든다.

> ⚠️ **투자 권유가 아니다.** 개인 판단을 돕는 참고 도구이며, 계약 전 현장 확인과 전문가 상담이 필요하다.

---

## 지금 어디까지 됐나

| 단계 | 상태 |
|---|---|
| 1. 인터뷰 | ✅ 완료 |
| 2. 설계 | ✅ 완료 — `docs/02-design/` |
| 3. 구현 | 🟡 **진행 중** — 도메인 로직·API·에이전트·프론트 골격 완료 |
| 4. 테스트 | ⬜ |
| 5. 모니터링 | ⬜ |
| 6. 최종점검 | ⬜ |

**테스트: 백엔드 170 passed · 프론트 15 passed · 프론트 빌드 성공**

### 아직 안 된 것 (중요)
- **PostGIS 리포지토리** — 현재 인메모리 구현만 있다. 로컬에 Docker 가 없어 DB 를 못 띄웠다
- **실제 데이터 수집** — 공공API 서비스키 미발급. 파싱 로직은 픽스처로 검증됨
- **세율 실제값** — `config/tax_rules.yaml` 이 비어 있어 자금 계산 API 는 **503 을 반환**한다(의도적)
- **로그인 화면** — 프론트에 미구현
- **서버 배포** — 하드닝 설계만 있고 미적용

---

## 30분 안에 돌려보기

### 필요한 것
- Python 3.12+, Node 20+
- (선택) Docker — 있으면 PostGIS 까지 띄울 수 있다

### 백엔드 테스트
```bash
cd backend
python -m pip install -r requirements.txt
python -m pytest              # 170 passed
```

### 프론트엔드
```bash
cd frontend
npm install
npm run build                 # 빌드 확인
npm run dev                   # http://localhost:5173
```
지도를 보려면 `frontend/.env` 에 카카오 JS 앱키가 필요하다(`.env.example` 참고).
**키가 없어도 앱은 뜨고**, 지도 자리에 이유가 표시된다.

### 백엔드 서버 (인메모리)
```bash
cd backend
export JWT_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export FIELD_ENCRYPTION_KEY=$(python -c "import secrets,string;a=string.ascii_letters+string.digits;print(''.join(secrets.choice(a) for _ in range(32)))")
uvicorn app.main:app --reload
```
> 데이터가 메모리에만 있어 재시작하면 사라진다. PostGIS 구현 전까지의 임시 상태다.

### 전체 스택 (Docker 필요)
```bash
cp .env.example .env          # 값 채우기
docker compose up -d
```

---

## 구조

```
backend/
  app/
    domain/        ★ 순수 비즈니스 로직 (DB·프레임워크 무관 → Docker 없이 테스트됨)
      affordability/   실구매 가능 금액 (LTV/DSR/DTI 이분탐색)
      valuation/       적정가 밴드 · 층 보정 · 환금성
      listings/        중복 제거 · 신뢰도
      rules/           세율 설정 로더 (출처 없으면 로딩 거부)
    agents/        런타임 전문가 에이전트 오케스트레이션
    api/           FastAPI 라우터 (얇게 — 계산 로직 없음)
    ingest/        공공 오픈API 수집기
    core/          암호화 · JWT · 설정
  migrations/      PostGIS 스키마
  tests/           pytest
frontend/          React + Vite (모바일 퍼스트)
config/            tax_rules.yaml (세율 — 출처·기준일자 필수)
docs/              1~6단계 산출물
team/              에이전트 팀 헌장 · 역할 정의
```

---

## 이 프로젝트에서 지키는 원칙

설계 문서 곳곳에 흩어져 있지만, 핵심은 이 다섯 가지다.

### 1. 숫자는 코드가, 설명은 LLM 이
세금·대출한도·시세 통계는 **결정론적 계산**으로 구한다. LLM 은 계산된 숫자를 문장으로 바꾸는 역할만.
> LLM 에 취득세를 물어보면 그럴듯하게 틀린다. 그리고 그 오류는 수천만 원 단위다.

### 2. 출처 없는 주장은 내보내지 않는다
모든 근거에 `{claim, source, as_of}` 가 붙는다. 세율은 코드에 없고 `config/tax_rules.yaml` 에서만 온다.
출처·기준일자가 없으면 **로딩 자체가 거부**된다.

### 3. 모르면 모른다고 한다
표본이 5건 미만이면 시세 밴드를 만들지 않는다. 입지 데이터가 없으면 "판단 보류"를 반환한다.
**빈칸이 틀린 답보다 낫다.**

### 4. 추정치를 확정치처럼 보이게 하지 않는다
국토부 실거래가에는 **동(棟) 정보가 없다.** 층·타입별은 실거래로 계산되지만
**동별은 좌표 기반 추정**이라 `confidence ≤ 0.6` 이고 금액으로 환산하지 않는다.
UI 에서도 `~` 접두 + 회색 + `추정` 배지로 구분한다.

### 5. 반대 근거를 함께 낸다
장점만 나열하는 추천은 반려된다. LLM 이 단점을 비워 보내면 시스템이 채운다.

---

## 개인정보 취급

자산·소득·대출 정보는 **앱단 AES-256-GCM** 으로 암호화해 저장한다.
- `pgcrypto` 를 쓰지 않는 이유: 키가 SQL 문에 실려 쿼리 로그에 남는다 → DB 가 뚫리면 키도 함께 털린다
- AAD 에 `user_id`+필드명을 묶어 **암호문을 다른 사용자 행에 복사하는 공격**을 차단한다
- **Claude API 프롬프트에 원본 금액을 보내지 않는다** — 계산 결과(한도·적합 여부)만 전달하고,
  호출 직전에 기계적으로 검사한다

자세한 내용: `docs/02-design/security.md`

---

## 문서

| 문서 | 내용 |
|---|---|
| `CLAUDE.md` | 프로젝트 단일 진실 소스 · 진행 상태 |
| `docs/01-interview/requirements.md` | 요구사항 (F1~F6) |
| `docs/02-design/architecture.md` | 시스템 구성 · 트래픽 흐름 |
| `docs/02-design/erd.md` | 데이터 모델 (**§0 에 F4 제약 설명**) |
| `docs/02-design/api-spec.md` | API 계약 |
| `docs/02-design/security.md` | 위협 모델 · 서버 하드닝 |
| `docs/02-design/agents/` | 전문가 에이전트 8종 명세 |
| `docs/02-design/ux/` | 모바일 퍼스트 UI/UX |
| `docs/03-build/implementation-plan.md` | 구현 계획 · 작업 분할 |
| `docs/03-build/*-review-log.md` | 코드·보안 리뷰 원장 (**미검증 영역 명시**) |
| `team/CHARTER.md` | 에이전트 팀 운영 규칙 |

---

## 다음 작업

1. **PostGIS 리포지토리 구현** + 마이그레이션 실검증
2. 공공API 서비스키 발급 → 실거래가 수집 실행
3. `config/tax_rules.yaml` 채우기 (공식 출처 대조 필수)
4. 로그인 화면 + 조건 입력 UI
5. 지도 마커·클러스터 렌더링
6. 서버 하드닝 후 배포 (`docs/02-design/security.md` §4)
