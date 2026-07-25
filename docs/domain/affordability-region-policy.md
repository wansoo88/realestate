# 실구매 가능액 — 권역(region_group) 판정 정책

> 작성: re-domain · 2026-07-25 · ORDER 2026-07-25-14-domain
> 근거: docs/domain/lending-rules-contract.md §1·§3.1, re-review 사전지침(2026-07-25)
> 대상: `backend/app/domain/affordability/{models,engine}.py`
> ⚠️ 정확성 판정(C1~C6 재감사)은 re-review 몫. 여기서 자기 PASS 선언하지 않는다.

## 왜 권역이 중요한가
수도권 주담대 **6억 절대한도**(6.27 대책)가 수도권 조건부라, 엔진이 권역을 모르면
한도가 안 걸려 **실구매 가능액이 과대 산정**된다 — 이 오더가 고치려는 바로 그 버그다.

## 3대 원칙 (re-review 사전지침 반영)

### 1. 안전한 기본값은 **수도권(캡 적용)**
이 제품 대상지역이 수도권 전체(서울·경기·인천)다. 사실상 전 매물이 수도권이므로,
권역을 모를 때 캡을 **끄는** 기본은 제품 범위와 거꾸로다(무캡=과대산정).
그래서 `PropertyFacts.effective_region_group` 의 최종 폴백은 **"수도권"** 이다.
비수도권은 **명시적 예외**로만 발생한다.

```
effective_region_group = region_group(명시) or 코드파생(target_region_code) or "수도권"
```

### 2. 권역은 **서버 판정값** — 사용자 입력 금지
`is_regulated_area` 처럼 클라이언트가 보내는 값이면, 사용자가 권역을 비수도권으로 바꿔
6억 캡을 우회하고 **예산을 부풀릴 수 있다 → G2 위반**(사용자가 유리하게 바꿀 수 있으면 근거가 아니다).
- `region_group` 을 **어떤 요청 스키마에도 추가하지 않았다**(AffordabilityIn 등 불변).
- 서버가 단지 좌표 → 법정동코드에서 판정한다: 앞 2자리 `11`/`41`/`28` → 수도권.
- 파생 헬퍼: `PropertyFacts.region_group_from_code(code)`.

### 3. 생성 지점 전부 캡 적용 (테스트초록 + 제품무캡 = 최악 방지)
`PropertyFacts` 생성 지점 두 곳이 모두 캡 대상이어야 한다:
| 지점 | 처리 |
|---|---|
| `engine.py` 기본값 `prop or PropertyFacts()` | region 미지정 → 기본 수도권 → 캡 적용 |
| `routes.py::/affordability` (`PropertyFacts(area_m2, is_regulated_area, purpose)`) | region 미지정 → 기본 수도권 → 캡 적용 |

→ **안전 기본값을 `effective_region_group` 에 내장**해, 두 지점 모두 별도 배선 없이 캡이 걸린다.
`test_기본값_무지정도_수도권캡이_적용된다` 가 "region 안 넘겨도 캡 적용"을 고정한다.

## 남은 배선 (re-be·re-arch — PM 경유)
- **단지별 정확 권역 주입**: 추천 플로우가 특정 단지를 다룰 땐, 그 단지의 PostGIS region
  (법정동코드)에서 `region_group` 또는 `target_region_code` 를 서버가 채워 `PropertyFacts` 로
  넘기는 게 이상적이다. 현재는 안전 기본(수도권)으로 동작하므로 **과대산정은 없다**(보수적).
  비수도권 단지를 정확히 구분하려면 이 배선이 필요하다. `routes.py`/스키마는 re-be 소유라
  이번에 손대지 않았다.
- **config 실값**: `lending.absolute_cap`·`stress_dsr` 실제 값은 re-data 가 채운다.
  채우기 전에는 캡/가산이 없는 것으로 동작(하위호환, 이전과 동일).
