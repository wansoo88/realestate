"""MVP 에이전트 파이프라인.

설계 근거: docs/02-design/agents/README.md §2

    [1] finance-tax-advisor   (규칙 계산 · LLM 없음)  → 예산 상한
    [2] listing-researcher    (DB/규칙)             → 후보 축소
    [3] valuation-trader · location-analyst (규칙 + LLM 설명)
    [4] portfolio-advisor     (LLM 종합)

순서가 중요하다. 예산 상한 없이 분석하면 **살 수 없는 집에 API 비용을 태운다.**
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.agents.base import (
    AgentOutputError,
    Evidence,
    Finding,
    PromptSafetyError,
    Risk,
    assert_no_secrets,
    data_block,
    insufficient,
    scan_injection,
    validate_finding,
)
from app.agents.llm import (
    DEFAULT_MAX_TOKENS,
    MAX_PROMPT_CHARS,
    LLMClient,
    LLMError,
)
from app.agents.scoring import (
    ScoreResult,
    build_axis_signals,
    defaulted_axes,
    normalize_weights,
    score_item,
    summary_notes,
)
from app.domain.affordability.budget import BudgetFn
from app.domain.affordability.models import AffordabilityResult
from app.domain.listings.dedup import ListingGroup, trust_score
from app.domain.location.analysis import evaluate_location
from app.domain.location.models import LocationAssessment, LocationFacts
from app.domain.redevelopment.analysis import (
    PURPOSE_LIVE,
    CostGuardError,
    RedevAssessment,
    assert_no_cost_estimate,
    assert_no_cost_topic,
    assess_redevelopment,
    contains_cost_topic,
    redact_cost_topic,
)
from app.domain.redevelopment.models import RedevProject
from app.domain.redevelopment.stages import STAGE_UNKNOWN
from app.domain.valuation.models import DongValuation, Liquidity, ListingRow, TradeRow
from app.domain.valuation.stats import (
    ask_gap_pct,
    dong_effect,
    fair_price_band,
    liquidity,
)
from app.domain.valuation.timeadjust import (
    SCOPE_SIDO,
    SCOPE_SIGUNGU,
    MarketIndex,
    adjustment_evidence,
    select_index,
)

logger = logging.getLogger("agents")

DISCLAIMER = ("투자 권유가 아니며 개인 판단을 돕는 참고 자료입니다. "
              "실제 계약 전 현장 확인과 전문가 상담을 권합니다.")

#: 실거래 신고 지연 — 모든 시세 판단에 붙는 상수 리스크
#: ⚠️ 30일은 **신고기한**이다(부동산거래신고법 제3조 제1항). "신고까지 최대 30일"이라고만
#:    말하면 30일이 지연의 상한처럼 읽히는데 그렇지 않다 — 기한 안에 낸 신고가 공개
#:    API 에 실리기까지 시간이 더 걸리고, 지각 신고도 있다(CR34-4). 우리는 그 추가분을
#:    재지 않았으므로 **숫자로 말하지 않는다.**
DELAY_RISK = Risk("medium",
                  "실거래는 계약일로부터 30일 이내에 신고하게 되어 있고 공개까지는 "
                  "시간이 더 걸립니다 — 최근 거래가 반영되지 않았을 수 있습니다.")

# --- 가격 근거 (price_basis) ------------------------------------------------
#
# 이 제품에서 **호가와 실거래는 같은 숫자가 아니다.**
#   listing = "지금 이 값에 살 수 있다"  (매도인이 부른 값 · 지금 존재하는 물건)
#   trade   = "최근 이 정도에 거래됐다"  (이미 끝난 거래 · 지금 살 수 있는 물건은 없음)
#
# 공공 API 에는 호가가 없다. 포털 수집이 막히면 `listing` 테이블이 통째로 비고,
# 호가를 요구하는 설계는 후보를 **구조적으로 0건**으로 만든다(CHARTER G4 위반).
# 그래서 실거래만으로도 후보를 세우되, **어느 쪽 근거인지 응답에 명시**한다(G2).
# 실거래 중위가를 호가처럼 위장하지 않는다 — 위장하는 순간 하류(프론트·리포트)가
# "지금 이 값에 살 수 있다"로 읽는다.
PRICE_BASIS_LISTING = "listing"
PRICE_BASIS_TRADE = "trade"

# --- 제외 사유 (excluded) ---------------------------------------------------
#
# 이 제품의 신뢰는 **"왜 이건 안 나왔지"에 답하는 것**에 달려 있다. 추천 목록만 주면
# 사용자는 자기가 아는 단지가 빠졌을 때 결과 전체를 의심한다. 그래서 떨어뜨린 후보를
# 사유와 함께 남기고, 저장·조회 경로로 끝까지 실어 보낸다(api-spec.md §5.2).
#
# ⚠️ 사유 문장에 **사용자 자산 원본 금액을 적지 않는다**(security.md §6 · SR4-2).
#    한도·초과분 같은 **파생값**까지가 허용선이다 — 원본 현금·소득은 애초에 이 계층에
#    들어오지 않는다(AnalysisContext 가 파생값만 갖는다). 러너가 그 위에 그물을 하나 더 건다.
EXCLUDED_NO_PRICE = "no_price_evidence"      # 호가 없음 + 실거래 표본 부족
EXCLUDED_OVER_BUDGET = "over_budget"         # 예산 초과
EXCLUDED_AVOIDED = "avoided"                 # 사용자가 기피한 조건에 해당(F5)
EXCLUDED_RANK_CUTOFF = "below_rank_cutoff"   # 분석은 통과했지만 상위 N 밖

#: 기피 조건 키 — 초기 단계 정비사업(api-spec.md §2 `avoid.redevelopment_early_stage`).
#: 계약에는 있었지만 판정 코드가 없어 **저장만 되고 아무 일도 하지 않던** 값이다.
AVOID_REDEV_EARLY = "redevelopment_early_stage"

#: 실거래 기준 후보에 붙는 표준 문구. UI 가 그대로 노출해도 되도록 완결형으로 둔다.
TRADE_BASIS_NOTE = ("현재 등록된 매물이 없습니다 — 최근 실거래 기준 추정가입니다. "
                    "실제 매수 가능 가격은 다를 수 있습니다.")


def trade_basis_note(band: Any) -> str:
    """실거래 기준 후보의 `price_note`. **시점까지 말한다**(CR34-5).

    `TRADE_BASIS_NOTE` 만으로는 부족하다 — 그 문장은 *가격 근거*(호가가 없다)만
    말하고 이 숫자가 **언제 시점의 값인지**는 말하지 않는다. 그런데 보정이 켜진 뒤로
    같은 문구가 두 가지 다른 값에 붙는다:
      · 보정됨   — 특정 기준월로 환산한 추정가
      · 보정 안 됨 — 6~36개월 거래를 시점 구분 없이 섞은 값(어느 시점도 아니다)
    두 값에 같은 말을 붙이면 사용자는 구분할 방법이 없다. 상수는 문구가 고정이라
    기준월을 담을 수 없으므로, 뒤에 한 문장을 **덧붙여** 만든다.

    ⚠️ 상수 자체는 그대로 둔다 — 다른 곳(테스트·프론트 문구 대조)이 그 문자열을
       접두로 본다. 여기서 하는 일은 **덧붙이기**지 바꾸기가 아니다.
    """
    ym = getattr(band, "as_of_label", None)
    if ym:
        return f"{TRADE_BASIS_NOTE} 이 금액은 {ym} 시점으로 환산한 값입니다."
    return (f"{TRADE_BASIS_NOTE} 시점 보정을 하지 못해 여러 시점의 거래를 섞은 값이라 "
            f"특정 시점의 가격이 아닙니다.")
#: 실거래 기준 후보의 판정 문구(호가 갭 판정을 대체한다).
TRADE_BASIS_VERDICT = "현재 매물 없음 — 최근 실거래 기준"


@dataclass
class Candidate:
    complex_id: int
    complex_name: str
    unit_type_id: int | None
    area_m2: float
    #: 이 단지의 법정동코드(`complex.region_code`, 10자리). **시점 보정의 유일한 입력**이다 —
    #: 시장지수는 지역별이라 이 값이 없으면 어느 지수를 쓸지 정할 수 없다.
    #: None 이면 보정하지 않고 그 사실이 밴드에 사유로 남는다(지수 1.0 으로 가정하지 않는다).
    region_code: str | None = None
    #: 대표 호가 그룹. **None 일 수 있다(1급 시민).**
    #: 공공 API 에는 호가가 없으므로 호가 0건인 단지도 실거래 기준으로 후보가 된다.
    #: ⚠️ 여기에 가짜 대표 호가를 만들어 끼우지 말 것 — 하류가 그걸 진짜 호가로 믿는다.
    group: ListingGroup | None = None
    trades: list[TradeRow] = field(default_factory=list)
    total_households: int | None = None
    listings: list[ListingRow] = field(default_factory=list)
    #: 입지 사실(학군·교통·인프라·유해요소). 리포지토리가 공간쿼리로 채워 넘긴다.
    #: 없으면 location-analyst 는 판단 보류를 낸다(지어내지 않는다).
    location: LocationFacts | None = None
    #: 매칭된 정비사업 구역. **None 은 '정비사업 없음'이 아니라 '확인되지 않음'이다**
    #: (수집 범위가 서울·인천뿐이다). 도메인이 그 구분을 문구로 낸다.
    redevelopment: RedevProject | None = None

    @property
    def price_basis(self) -> str:
        """이 후보의 가격 근거가 호가인가 실거래인가."""
        return PRICE_BASIS_LISTING if self.group is not None else PRICE_BASIS_TRADE

    @property
    def ask_price_krw(self) -> int | None:
        """대표 호가. 호가가 없으면 **None** — 실거래 중위로 채우지 않는다."""
        return self.group.representative.ask_price_krw if self.group is not None else None

    @property
    def target_floor(self) -> int | None:
        """층 보정 대상 층. 호가가 없으면 대상 층 자체가 없다(보정하지 않는다)."""
        return self.group.representative.floor if self.group is not None else None


#: 지역코드 자릿수. `complex.region_code` 는 10자리 법정동코드이고, 지수 표
#: (`market_price_index`)의 키는 **시군구 5자리 · 시도 2자리**다(migration 015).
SIGUNGU_CODE_LEN = 5
SIDO_CODE_LEN = 2


def region_index_keys(region_code: str | None) -> tuple[str | None, str | None]:
    """법정동코드 → (시군구 키, 시도 키). 자릿수가 모자라면 그 층위는 **None**.

    반쪽짜리 코드로 억지 조회를 하지 않는다 — '11'만 있는 값에서 5자리 키를 만들면
    엉뚱한 시군구 지수를 붙이게 된다.
    """
    code = (region_code or "").strip()
    return (code[:SIGUNGU_CODE_LEN] if len(code) >= SIGUNGU_CODE_LEN else None,
            code[:SIDO_CODE_LEN] if len(code) >= SIDO_CODE_LEN else None)


def candidate_index(candidate: Candidate,
                    indexes: dict[str, Any] | None) -> MarketIndex | None:
    """이 후보에 쓸 시장지수. **키 조회 + 사유가 남게 하는 폴백**만 한다.

    어느 지수를 쓸지 고르는 **정책은 도메인**에 있다(`timeadjust.select_index`:
    커버리지를 통과한 것 중 기준월이 가장 최근인 지수, 같으면 시군구). 그 규칙을 여기
    배선 계층에 두면 도메인이 공개 API 로 다른 정책을 선언하게 되고, 다음 사람이
    `fair_price_band(index=select_index(...))` 라는 **정식 경로**로 옛 정책을 타게 된다
    (CR33-2 — 그 경로가 실제로 남산타운 −12.3% 를 냈다).

    ⚠️ **`select_index` 가 None 을 줘도 그대로 None 을 돌려주지 않는다.**
    `fair_price_band` 는 `index=None` 이면 `time_adjustment` 자체를 비운 채 밴드를
    내는데, 그건 "보정하지 않았다"가 아니라 **"보정을 시도조차 안 했다"** 를 뜻한다
    (models.PriceBand 주석). 조회를 해 놓고 그 값을 쓰면 왜 보정이 안 됐는지가
    응답에서 사라진다 — 이 저장소가 가장 경계하는 조용한 실패다.
    그래서 가진 지수를 **그대로 넘겨** `adjust_trades` 가 사유(REASON_NO_INDEX ·
    REASON_LOW_COVERAGE …)를 남기게 한다.

    `indexes is None`(조회 자체를 안 함)일 때만 None 을 돌려준다.
    """
    if indexes is None:
        return None
    sgg_key, sido_key = region_index_keys(candidate.region_code)
    sgg = indexes.get(sgg_key) if sgg_key else None
    sido = indexes.get(sido_key) if sido_key else None
    chosen = select_index(candidate.trades, sigungu=sgg, sido=sido)
    if chosen is not None:
        return chosen
    # 어느 쪽도 커버리지 문턱을 못 넘겼다. 사유를 남길 수 있게 **점이 있는 쪽**을 우선
    # 넘긴다(빈 지수를 넘기면 '지수 없음'이라는 덜 정확한 사유가 나간다).
    with_points = next((idx for idx in (sgg, sido) if idx is not None and idx.points),
                       None)
    if with_points is not None:
        return with_points
    if sgg is not None or sido is not None:
        return sgg or sido                 # 조회됐지만 비어 있는 지수 → REASON_NO_INDEX
    # 이 지역은 조회 결과가 아예 없다(배치 미실행 · 조회 실패 · 지역코드 미상).
    # **빈 지수를 만들어 넘긴다.** 값을 지어내는 게 아니다 — 점이 0개라 보정은 절대
    # 일어나지 않고, 오직 "조회했고 없었다"를 밴드에 **사유로 남기기 위한** 자리다.
    # 여기서 None 을 돌려주면 `time_adjustment` 가 통째로 비어 '시도조차 안 함'과
    # 구분되지 않는다(= 조용한 실패).
    return MarketIndex(region_code=sgg_key or sido_key or "",
                       scope=SCOPE_SIGUNGU if sgg_key else SCOPE_SIDO, points={})


def reference_band(candidate: Candidate, as_of: dt.date, *,
                   indexes: dict[str, Any] | None = None):
    """이 후보의 적정가 밴드. 호가가 있으면 그 층으로 보정한다.

    호가가 없으면 보정할 대상 층이 없으므로 단지·면적 기준 밴드를 그대로 쓴다.

    `indexes` 를 주면 창 안의 거래를 **각각 기준월 수준으로 환산**한 뒤 분위수를 낸다
    (시점 혼합 보정 — `app/domain/valuation/timeadjust.py`). 주지 않으면 예전과 같은 값이다.
    ⚠️ 이 인자를 빠뜨리면 **아무 동작 변화 없이** 밴드가 조용히 과소평가된다(서울 ≈10%).
       그래서 파이프라인은 `ctx.market_indexes` 를 반드시 넘긴다.
    """
    return fair_price_band(candidate.trades, area_m2=candidate.area_m2, as_of=as_of,
                           target_floor=candidate.target_floor,
                           index=candidate_index(candidate, indexes))


def reference_price_krw(candidate: Candidate, band: Any) -> int | None:
    """예산 판정·표시에 쓸 **기준가**와 그 근거를 정한다.

    호가가 있으면 호가(사실), 없으면 실거래 중위(추정)다. 둘 다 없으면 **None** —
    가격 근거가 없는 후보는 예산을 따질 수도, 추천할 수도 없다(지어내지 않는다).
    """
    if candidate.group is not None:
        return candidate.ask_price_krw
    return band.median_krw if band.available else None


@dataclass
class AnalysisContext:
    """파이프라인 입력.

    ⚠️ **1차 방어는 이 구조다.** 이 컨텍스트는 사용자 자산 **원본 금액을 담지 않고**
    `affordability` **계산 결과(파생값)** 만 가진다. 각 Finding 도 한도·부대비용 같은
    파생값만 프롬프트에 싣는다. 즉 원본 자산은 애초에 LLM 경로로 갈 수 없다.
    `forbidden_amounts` 는 그 위에 얹는 **best-effort tripwire** 일 뿐 주 방어가 아니다.
    """

    affordability: AffordabilityResult
    candidates: list[Candidate]
    avoid: dict[str, Any] = field(default_factory=dict)
    #: 매수 목적 — `live`(실거주) | `invest`(투자). api-spec §2 와 같은 값.
    #: ⚠️ 정비사업 판정이 이 값에 따라 **정반대**가 된다(관리처분 단계는 투자에는
    #:    '확실하지만 이미 반영', 실거주에는 '이주 임박 — 부적합'이다).
    purpose: str = PURPOSE_LIVE
    #: 사용자 조건 가중치(`user_preference.weights`) — 가격·입지·가치·리스크·재건축.
    #: **여기서 순위가 실제로 바뀐다.** 비어 있으면 기존 동작(신뢰도 가중 평균)으로
    #: 폴백하고 그 사실을 notes 에 남긴다(app/agents/scoring.py).
    weights: dict[str, Any] = field(default_factory=dict)
    as_of: dt.date = field(default_factory=dt.date.today)
    #: tripwire 검사값(프롬프트 구성에는 쓰지 않는다). 비워두면 파이프라인이
    #: affordability 파생값으로 보강하고, 그래도 비면 fail-loud 로 막는다.
    forbidden_amounts: list[int] = field(default_factory=list)
    #: 지역별 시장지수 캐시 — `{지역코드: MarketIndex}` (시군구 5자리 · 시도 2자리 키).
    #: 적정가 밴드의 **시점 보정**에 쓴다(migration 015 · timeadjust.py).
    #:
    #: ⚠️ **None 과 {} 는 다르다.**
    #:   · `None` = 지수를 **조회조차 하지 않았다**. 밴드는 예전 값 그대로이고
    #:     `time_adjustment` 도 비어 있다(단위 테스트·구형 호출부).
    #:   · `{}`   = 조회했는데 하나도 없었다(배치 미실행 등). 보정은 안 되지만
    #:     **사유가 밴드에 남는다** — 운영에서 이 둘은 완전히 다른 사고다.
    #: ⚠️ 후보 루프 안에서 채우지 않는다. 러너가 후보 전체의 지역을 모아 **한 번에**
    #:    조회해 넘긴다(`recommend.load_market_indexes`). 후보마다 조회하면
    #:    후보 200건 × 2층위 = 400 쿼리가 된다.
    market_indexes: dict[str, Any] | None = None
    #: **적용할 예산 상한**(원). 사용자가 희망 매매가를 지정하면 그 값이 온다.
    #: None 이면 `affordability.max_purchase_krw`(최대 실구매 가능 금액)를 쓴다 — 기존 동작.
    #:
    #: ⚠️ 왜 필드를 따로 두는가 (ORDER 2026-07-26)
    #: 예전에는 파이프라인이 **항상** `affordability.max_purchase_krw` 로만 예산을 판정해서,
    #: API 의 `budget_override_krw` 가 후보 **조회**에만 닿고 **제외 판정에는 닿지 않았다**.
    #: 그 결과 희망가를 자기 한도보다 높게 잡으면 조회는 통과한 후보가 전부
    #: "예산 초과"로 잘려 **결과가 통째로 비었다** — 슬라이더를 올릴수록 결과가 사라지는
    #: 형태라 원인을 짐작할 수도 없다. `affordability` 를 조작해 우회하지 않는 이유는
    #: 그러면 finance finding 이 희망가를 "실구매 가능 금액"이라고 잘못 말하기 때문이다.
    budget_krw: int | None = None
    #: **후보 면적별 예산 상한 조회기**(면적 → 상한). 있으면 이것이 정본이다.
    #:
    #: ⚠️ 왜 한 숫자로는 안 되는가 (CR39-2, 2026-07-30)
    #: 자산으로 계산한 상한은 **전용면적의 함수**다 — 취득세 농특세가 85㎡ 를 경계로
    #: 붙는다(운영 세율 실측 1,026,560,000 vs 1,024,580,000). 그런데 후보의 단위는
    #: `api-spec §5` 대로 **단지 × 면적대**라서, 한 추천 안에 34㎡ 와 120㎡ 가 함께 있다.
    #: 예전에는 `PropertyFacts()` 기본값 84.0 으로 만든 한 숫자로 전부를 판정했고,
    #: 그 방향은 **관대**였다(84㎡ 상한이 더 크다) — 즉 *못 사는 후보가 통과*했다.
    #: 지도는 CR37-1 에서 이미 고쳤고, 이 필드가 추천을 **같은 함수**로 데려온다
    #: (`app/domain/affordability/budget.py` — 계산은 세율 구간별로 1회씩만 돈다).
    #:
    #: `None`(미지정)이면 옛 계약대로 `budget_krw`/`affordability` 의 한 숫자를 쓴다 —
    #: 단위 테스트·구형 호출부를 위한 폴백이고, 실경로(러너)는 항상 채워 넘긴다.
    budget_at: BudgetFn | None = None

    @property
    def effective_budget_krw(self) -> int:
        """예산 판정에 쓰는 **한 숫자**(요약·폴백용). 0 이면 '예산 제한 없음'.

        ⚠️ 후보 판정에 이 값을 직접 쓰지 말 것 — `budget_cap_krw(면적)` 을 쓴다.
        희망 매매가를 준 경우에는 두 값이 같다(희망가는 면적과 무관한 금액 하나다).
        """
        if self.budget_krw is not None:
            return self.budget_krw
        return self.affordability.max_purchase_krw

    def budget_cap_krw(self, area_m2: float | None) -> int | None:
        """**이 면적**에 적용할 예산 상한.

        · 양수  = 그 금액이 상한
        · `0`   = 예산 제한 없음(자산 미입력 등) — 판정하지 않고 통과시킨다
        · `None` = 상한을 세울 수 없다(면적 미상 + 자산 기준) — **판정하지 않는다**.
          84 를 가정해 채우면 다른 면적의 한도로 내린 판정이 그 후보의 판정이 된다.
          호출부는 이 경우를 **세어서 말해야 한다**(조용히 통과시키지 않는다).
        """
        if self.budget_at is not None:
            return self.budget_at(area_m2)
        return self.effective_budget_krw


# ---------------------------------------------------------------------------
# [1] finance-tax-advisor — LLM 없음
# ---------------------------------------------------------------------------

def finance_finding(result: AffordabilityResult) -> Finding:
    evidence = [
        Evidence(claim=e.get("claim", ""), source=e.get("source", ""),
                 as_of=e.get("as_of"), source_url=e.get("source_url"))
        for e in result.evidence
    ]
    if not evidence:
        return insufficient("finance-tax-advisor", ["세율 근거 없음"])

    return validate_finding(Finding(
        agent_id="finance-tax-advisor",
        # 라벨은 화면과 **같은 말**이어야 한다. 프론트가 "최대 실구매 가능 금액"으로 부르는데
        # 여기만 "실구매 가능"이면 같은 숫자가 두 이름으로 보인다(FIN-1 지적).
        verdict=f"최대 실구매 가능 {result.max_purchase_krw:,}원",
        rationale=(
            f"취득 부대비용 {result.costs.total_krw:,}원을 포함해 "
            f"{result.max_purchase_krw:,}원까지 가능합니다. "
            f"한도를 묶는 것은 {result.binding_constraint} 입니다."
        ),
        evidence=evidence,
        risks=[Risk("medium", "실제 한도는 금융기관 심사·신용등급에 따라 달라집니다.")],
        score=None,
        confidence=0.95,
    ))


# ---------------------------------------------------------------------------
# [2] listing-researcher — 규칙
# ---------------------------------------------------------------------------

def listing_finding(candidate: Candidate, median_krw: int | None,
                    as_of: dt.date) -> Finding:
    """매물 신뢰도(= 리스크 축). **출처에 따라 판정 가능 여부가 갈린다.**

    수집 호가 → 예전과 같다(중복 등록·등록 경과일·시세 갭·최근 확인).
    사용자 수동 입력 → `trust_score` 가 `None` 을 준다. 그 사유를 그대로 내보내고
                      **점수를 만들지 않는다**(리스크 축은 '미반영'이 된다).

    ⚠️ 여기서 점수를 지어내면 무슨 일이 벌어지나 (2026-07-29 실측)
       사용자 입력 그룹은 신뢰도 신호 넷 중 셋이 침묵하고 "최근 확인됨" 가산만 붙어
       **만점**이 나온다. 같은 후보(호가가 적정가보다 +9.3% 비쌈)에서 리스크 축
       100.0점(실효비중 25%)이 붙어 총점 67.0 — 안 붙이면 56.0 이다.
       즉 **비싼 매물을 손으로 입력할수록 추천 점수가 올라간다.**
    """
    if candidate.group is None:
        # 평가할 매물 자체가 없다. "정상 매물"도 "허위 의심"도 아니다 —
        # 공공 API 에는 호가가 없으므로 이건 **정상적인 데이터 없음**이다(G4).
        return insufficient(
            "listing-researcher",
            ["현재 등록된 호가 매물 없음 — 공공 오픈API 에는 호가가 포함되지 않습니다"])

    score, signals = trust_score(candidate.group,
                                 median_price_krw=median_krw, as_of=as_of)
    if score is None:
        # 판정 못 한 것을 판정한 것처럼 내보내지 않는다. 사유는 도메인이 준 그대로 —
        # 여기서 다시 쓰면 두 곳이 갈라지고, 갈라지면 한쪽만 고쳐진다.
        return insufficient("listing-researcher", list(signals))
    rep = candidate.group.representative
    # 중개사 중복 등록 수는 **수집 건수**다. 사용자가 자기 손으로 적은 한 건이 "중개사
    # 하나 더"로 세어지면, 사용자가 자기 입력으로 중복 등록 신호를 만든 꼴이 된다.
    listed_count = len(candidate.group.collected)

    risks: list[Risk] = []
    if score < 0.7:
        risks.append(Risk("medium", "매물 신뢰도가 낮습니다: " + "; ".join(signals)))
    if listed_count >= 4:
        risks.append(Risk("low",
                          f"{listed_count}개 중개사에 중복 등록되어 있습니다."))

    return validate_finding(Finding(
        agent_id="listing-researcher",
        verdict="확인 필요" if score < 0.7 else "정상 매물",
        rationale=(f"호가 {rep.ask_price_krw:,}원, {rep.floor}층. "
                   + ("특이사항: " + "; ".join(signals) if signals else "특이 신호 없음.")),
        evidence=[Evidence(claim=f"활성 매물 {listed_count}건",
                           source="포털 매물 수집", as_of=as_of.isoformat())],
        risks=risks,
        score=round(score * 100, 1),
        confidence=0.8,
    ))


# ---------------------------------------------------------------------------
# [3] valuation-trader — 규칙 계산 + (선택) LLM 설명
# ---------------------------------------------------------------------------

def candidate_liquidity(candidate: Candidate, as_of: dt.date) -> Liquidity:
    """이 후보의 환금성. **가치 축 점수의 원천**이라 파이프라인과 finding 이 같은 값을 본다.

    한 곳에서 계산해 양쪽에 넘긴다 — rationale 에 적힌 등급과 점수가 서로 다른 거래를
    보고 있으면 사용자는 어느 쪽도 검증할 수 없다.
    """
    return liquidity(candidate.trades, candidate.listings,
                     candidate.total_households, as_of=as_of)


def valuation_finding(candidate: Candidate, as_of: dt.date, *,
                      band: Any | None = None, liq: Liquidity | None = None,
                      indexes: dict[str, Any] | None = None) -> Finding:
    """시세 판정. **호가 유무에 따라 판정 축이 다르다.**

    호가 있음 → 호가 갭(ask_gap)으로 "적정가 상단/하단"을 판정한다.
    호가 없음 → 비교할 호가가 없다. 갭을 계산하지 않고(None) **적정가 밴드 자체**를
                근거로 제시한다. 없는 숫자를 만들어 내면 그 순간 G2 위반이다.

    `band` 를 받으면 그대로 쓴다(파이프라인이 한 번 계산해 넘긴다 — 같은 숫자를 두 번
    만들지 않는다). 직접 부르는 호출부는 `indexes` 로 시점 보정을 켤 수 있다.
    """
    band = reference_band(candidate, as_of, indexes=indexes) if band is None else band
    if not band.available:
        return insufficient("valuation-trader", [band.reason or "실거래 표본 부족"])

    ask = candidate.ask_price_krw
    # ⚠️ 호가가 없으면 갭은 **None** 이다. 실거래 중위를 호가 자리에 넣어 0% 를 만들면
    #    "적정가 범위"라는 근거 없는 판정이 생긴다(비교 대상이 자기 자신이므로).
    gap = ask_gap_pct(ask, band) if ask is not None else None
    liq = candidate_liquidity(candidate, as_of) if liq is None else liq

    if ask is None:
        verdict = TRADE_BASIS_VERDICT
    elif gap is None:
        verdict = "판단 보류"
    elif gap <= -10:
        verdict = "적정가 하단 — 급매 가능"
    elif gap >= 10:
        verdict = "적정가 상단"
    else:
        verdict = "적정가 범위"

    # F4: 동(棟)별 편차를 실거래 aptDong 으로 실측한다.
    # ⚠️ 실거래 기반이라 **호가 유무와 무관하게** 동작한다. 호가 없는 후보에서도 살아 있어야 한다.
    # ⚠️ 밴드 기간(band.period_months)을 넘기지 않는다 — aptDong 은 등기 후에만 채워져서
    #    최근 6개월 창에서는 동 정보가 33~58% 로 떨어지고, 거래가 많은 단지일수록 밴드가
    #    6개월에 멈춰 실측이 실패한다(실데이터 검증: 6개월 4/8 → 24개월 8/8).
    #    dong_effect 는 자체 기본 창(DONG_PERIOD_MONTHS)을 쓴다.
    dong = dong_effect(candidate.trades, area_m2=candidate.area_m2, as_of=as_of)

    risks = [DELAY_RISK]
    if band.expanded:
        risks.append(Risk("low",
                          f"표본이 부족해 최근 {band.period_months}개월까지 확장해 계산했습니다."))
    if liq.grade == "나쁨":
        risks.append(Risk("medium", "거래 회전율이 낮아 매도에 시간이 걸릴 수 있습니다."))

    if ask is None:
        # 살 수 있는 물건이 확인되지 않았다는 사실 자체가 리스크다. 숨기지 않는다.
        risks.append(Risk("medium",
                          "현재 매수 가능한 매물이 확인되지 않았습니다. "
                          "아래 가격은 호가가 아니라 최근 실거래 기준 추정입니다."))

    # 시점 보정을 **시도했는데 못 한** 경우. 조용히 넘기지 않는다 —
    # 이 밴드는 6~36개월 거래를 시점 구분 없이 섞은 값이고, 상승장에서는 그만큼
    # 낮게 나온다(실측: 서울 ≈10% · 경기 ≈3% · 인천 ≈0.9%). 호가가 없는 후보에서는
    # 이 값이 곧 **예산 판정 기준가**라 표시 오차로 끝나지 않는다.
    if band.time_adjustment is not None and not band.time_adjustment.applied:
        risks.append(Risk(
            "medium",
            f"적정가 밴드에 시점 보정을 적용하지 못했습니다"
            f"({band.time_adjustment.reason}). 최근 {band.period_months}개월 거래를 "
            f"시점 구분 없이 섞은 값이라 상승장에서는 실제 시세보다 낮게 나옵니다."))

    # 점수: 갭이 작을수록 좋다(0% 기준). ±20% 를 0점 경계로 본다.
    # ⚠️ 호가가 없으면 **점수를 매기지 않는다(None)**. 매길 축(호가 vs 적정가)이 없다.
    #    0 점을 주면 "나쁘다"로 읽히고, 임의 점수를 주면 근거 없는 서열이 생긴다.
    score = max(0.0, min(100.0, 100.0 - abs(gap) * 5)) if gap is not None else None

    # 시점 보정을 했으면 **밴드의 숫자가 언제 시점 값인지**를 문장에 박는다.
    # "현재 시세"라고 쓰지 않는다 — 기준월은 완결된 가장 최근 달이고, 그 사실이
    # 사용자가 이 숫자를 얼마나 믿을지 정하는 근거다(timeadjust 규칙 3).
    ym = band.as_of_label
    median_label = (f"{ym} 시점 환산 중위 {band.median_krw:,}원" if ym
                    else f"중위 {band.median_krw:,}원")
    if ask is not None:
        rationale = (
            f"동일 타입 {band.sample_size}건 {median_label} 대비 "
            f"호가 {ask:,}원은 {gap:+.1f}% 입니다. 환금성은 {liq.grade}."
        )
    else:
        rationale = (
            f"{TRADE_BASIS_NOTE} 동일 타입 최근 {band.period_months}개월 실거래 "
            f"{band.sample_size}건 기준 적정가 밴드는 "
            f"{band.p25_krw:,}~{band.p75_krw:,}원({median_label})입니다. "
            f"비교할 호가가 없어 호가 갭은 계산하지 않았습니다. 환금성은 {liq.grade}."
        )
    # 근거 문구는 밴드가 직접 만든다(`PriceBand.to_evidence`) — 보정된 숫자를 여기서
    # "중위 실거래가"라고 다시 이름 붙이면 **다른 값을 같은 이름으로 부르는** 셈이 된다.
    evidence = [
        Evidence(claim=e["claim"], source=e["source"], as_of=e["as_of"],
                 data_rows=e.get("data_rows"))
        for e in band.to_evidence(as_of=as_of)
    ]
    # 보정을 실제로 한 경우에만 '무엇으로 얼마나 옮겼는지'를 근거로 덧붙인다.
    # 보정하지 않았으면 `adjustment_evidence` 가 빈 목록이다(없는 근거를 만들지 않는다).
    if band.time_adjustment is not None:
        evidence += [
            Evidence(claim=e["claim"], source=e["source"], as_of=e["as_of"],
                     data_rows=e.get("data_rows"))
            for e in adjustment_evidence(band.time_adjustment)
        ]
    # 동별 실측이 있으면 근거와 문구에 싣는다. 실측이 아니면(폴백) 지어내지 않는다.
    if dong.available:
        top = dong.dongs[0]
        rationale += (f" 동별로는 {top.dong}동이 단지 평균 대비 {top.vs_complex_pct:+.1f}%"
                      f"(실거래 {top.sample_size}건, 동 정보 {dong.coverage_pct}%)입니다.")
        evidence = (evidence or []) + [
            Evidence(claim=e["claim"], source=e["source"], as_of=e["as_of"],
                     data_rows=e["data_rows"])
            for e in dong.to_evidence(as_of=as_of)
        ]

    return validate_finding(Finding(
        agent_id="valuation-trader",
        verdict=verdict,
        rationale=rationale,
        evidence=evidence,
        risks=risks,
        score=score,
        confidence=0.85,
    ))


def _price_band_dict(band: Any) -> dict[str, Any] | None:
    """적정가 밴드를 추천 아이템 형태로 직렬화.

    호가가 없는 후보에게는 **이 밴드가 유일한 가격 근거**다. 갭 숫자를 지어내는 대신
    밴드 자체(p25~p75·표본·기간·확장 여부)를 그대로 보여 준다 — 근거의 강도를
    사용자가 직접 볼 수 있게("확신의 농도").
    """
    if band is None or not band.available:
        return None
    adj = band.time_adjustment
    return {
        "p25_krw": band.p25_krw,
        "median_krw": band.median_krw,
        "p75_krw": band.p75_krw,
        "sample_size": band.sample_size,
        "period_months": band.period_months,
        "expanded": band.expanded,
        "source": "국토교통부 실거래가",
        # --- 시점 계약 (이 숫자는 **언제** 시점 값인가) ---------------------
        # as_of_ym      : 보정했으면 기준월('2026-06'), 아니면 **null**.
        #                 null 은 "지금 시세"가 아니라 **"시점을 말할 수 없다"** 이다 —
        #                 6~36개월 거래를 섞은 값이라 어느 달의 가격도 아니다.
        # time_adjusted : 이 밴드가 실제로 환산된 값인가. 표시 문구가 여기서 갈린다.
        # time_adjustment: 시도했으면 결과(성공/실패+사유), 시도조차 안 했으면 null.
        #                 ⚠️ null 과 `{"applied": false}` 를 같게 다루지 말 것.
        "as_of_ym": band.as_of_label,
        "time_adjusted": band.is_time_adjusted,
        "time_adjustment": ({
            "applied": adj.applied,
            "reference_ym": adj.reference_ym,
            "scope": adj.scope,
            "region_code": adj.region_code,
            "shift_pct": adj.shift_pct,
            "coverage_pct": adj.coverage_pct,
            "sample_size": adj.sample_size,
            "basis": adj.basis,
            "reason": adj.reason,
            "note": adj.note(),
        } if adj is not None else None),
    }


def _dong_valuation_dict(d: DongValuation | None) -> dict[str, Any] | None:
    """F4 동별 실측을 추천 아이템 형태로 직렬화.

    실측(available)이면 basis=trade_measured·높은 신뢰로, 폴백이면 사유를 명시한다.
    실거래 자체가 부족해 valuation 이 나오지 않은 경우(d is None)는 필드를 비운다.
    """
    if d is None:
        return None
    if not d.available:
        return {
            "available": False,
            "method": d.method,          # 표본부족 | 동표본부족 | 동정보없음
            "confidence": 0.0,
            "coverage_pct": d.coverage_pct,
            "reason": d.reason,
            "note": "동별 판단은 좌표추정 폴백 대상입니다.",
        }
    return {
        "available": True,
        "method": d.method,              # 실측(aptDong)
        "basis": "trade_measured",
        "confidence": 0.85,              # 실거래 실측 → 높은 신뢰
        "coverage_pct": d.coverage_pct,
        "period_months": d.period_months,
        "dongs": [
            {"dong": s.dong, "vs_complex_pct": s.vs_complex_pct,
             "sample": s.sample_size, "median_ppm_krw": s.median_ppm_krw}
            for s in d.dongs
        ],
    }


# ---------------------------------------------------------------------------
# [3] location-analyst — 공간쿼리 결과를 근거로. 데이터 없으면 판단 보류
# ---------------------------------------------------------------------------

def _assessment_to_finding(assessment: LocationAssessment) -> Finding:
    """입지 종합 판정을 Finding 으로. 근거가 하나도 없으면 판단 보류."""
    if not assessment.excluded and not assessment.has_evidence:
        return insufficient("location-analyst",
                            list(assessment.missing)
                            or ["입지 판단에 쓸 실측 데이터 부족"])

    evidence = [Evidence(claim=e["claim"], source=e["source"], as_of=e.get("as_of"))
                for e in assessment.evidence]
    risks = [Risk(r["severity"], r["detail"]) for r in assessment.risks]

    if assessment.excluded:
        # 기피 조건 해당 — 근거가 아니라 제외 사유를 남긴다.
        return validate_finding(Finding(
            agent_id="location-analyst",
            verdict=assessment.verdict,
            rationale=assessment.rationale,
            evidence=evidence or [Evidence(
                claim=assessment.rationale, source="유해요소 반경 판정", as_of=None)],
            risks=[Risk("high", r) for r in assessment.exclusion_reasons] or risks,
            score=None,
            confidence=assessment.confidence,
        ))

    return validate_finding(Finding(
        agent_id="location-analyst",
        verdict=assessment.verdict,
        rationale=assessment.rationale,
        evidence=evidence,
        risks=risks,
        score=assessment.score,
        confidence=assessment.confidence,
    ))


def _nearest_station_dict(assessment: LocationAssessment | None) -> dict[str, Any] | None:
    """최근접 역 — **입지 분석이 이미 잰 값을 그대로 노출**한다(재계산하지 않는다).

    화면이 "🚇역세권" 배지를 달려면 거리가 필요하다. 그런데 **판정(500m 이내인가)이
    아니라 값(m)을 계약으로 둔다**:
      · 임계값은 표시 관례라 바뀐다. 판정을 서버가 굳혀 보내면 과거 job 의 payload 에
        옛 임계값이 그대로 저장돼 되돌릴 수 없다(payload 는 실행 결과 스냅샷이다).
      · 값이 없으면 `null` — "역이 없다"가 아니라 "모른다"다. 판정 boolean 만 주면
        모름과 아님이 같은 false 로 뭉개진다.
    거리는 **직선거리**(geography)다. 도보 시간이 아니므로 `basis` 로 못박는다.
    """
    if assessment is None:
        return None
    ns = (assessment.transit or {}).get("nearest_station")
    if not ns or ns.get("distance_m") is None:
        return None
    return {
        "name": ns.get("name"),
        "distance_m": round(float(ns["distance_m"]), 1),
        "line_count": ns.get("line_count"),
        "lines": list(ns.get("lines") or []),
        "basis": "straight_line",
    }


def location_finding(candidate: Candidate, as_of: dt.date, *,
                     avoid: Iterable[str] | None = None) -> Finding:
    """입지 판정. 입지 사실이 없으면 지어내지 않고 판단 보류."""
    if candidate.location is None:
        return insufficient("location-analyst",
                            ["입지 데이터(학군·교통·인프라) 미수집"])
    assessment = evaluate_location(candidate.location, avoid=avoid, as_of=as_of)
    return _assessment_to_finding(assessment)


# ---------------------------------------------------------------------------
# [3] redevelopment-analyst — 정비사업 단계 → 리스크-수익 프로파일
#
# ⚠️ 이 에이전트는 **점수를 한 방향으로 밀지 않는다.** 같은 '관리처분' 단계가
#    투자에는 "확실하지만 이미 가격에 반영", 실거주에는 "이주 임박 — 부적합"이다.
#    그래서 항상 `why`(상방)와 `why_not`(하방)을 **둘 다** 만든다.
# ⚠️ 추가분담금 **금액은 우리 코드가 만들지 않는다.** 도메인이 문장을 만들 때
#    `assert_no_cost_estimate` 가 막고, 여기서 finding 으로 옮길 때 **한 번 더** 막는다.
#    LLM 경로는 다르게 다룬다 — 재료를 아예 주지 않고, 주제어가 나오면 요약을 폐기한다
#    (`portfolio_summary` 참조). 완전한 차단을 주장하지 않는다(CR30-1).
# ---------------------------------------------------------------------------
AGENT_REDEV = "redevelopment-analyst"

#: 분담금 lint 가 발화해 이 후보의 재건축 블록만 내려놓았을 때의 사유.
#: **'정비사업이 없다'가 아니라 '이번 실행에서 판정을 내지 못했다'** 이다 —
#: 미확보(NO_PROJECT_REASON)와 문구를 구분해야 사용자가 원인을 짐작할 수 있다.
COST_GUARD_DEGRADED_REASON = (
    "정비사업 판정 문장이 내부 금액 검사에 걸려 이 단지의 재건축 분석만 내려놓았습니다 "
    "— '정비사업이 없다'는 뜻이 아니라 '이번 분석에서 판정하지 못했다'는 뜻입니다. "
    "정비사업 여부는 관할 구청 주거정비과 또는 정비사업 정보몽땅에서 확인하세요."
)


#: `detail` 에 남기는 강등 표식. 문구가 아니라 **이 키**로 센다 —
#: 사유 문장으로 세면 문구를 다듬는 순간 집계가 조용히 0이 된다.
COST_GUARD_DETAIL_KEY = "cost_guard_blocked"


def is_cost_guard_degraded(assessment: RedevAssessment) -> bool:
    """이 판정이 분담금 방어 때문에 내려간 것인가(= 미확보와 구분된다)."""
    return bool((assessment.detail or {}).get(COST_GUARD_DETAIL_KEY))


def _cost_guard_degraded() -> RedevAssessment:
    """분담금 방어가 걸린 후보의 표준 반환 — **판정만 비우고 후보는 살린다.**

    ⚠️ **진단문(`str(exc)`)을 응답에 싣지 않는다** (SR27-1 · CR32-4, 2026-07-28)
    -------------------------------------------------------------------------
    예전에는 `detail["cost_guard_error"]` 에 예외 문자열을 담았다. 그런데 그 문자열은
    `주제어 '분담' + 금액 '1억 2천만 원'` 처럼 **가드가 막은 금액을 그대로 인용**하고,
    `_redev_dict → payload → _item_to_dict` 를 타고 사용자 카드까지 나갔다(실측).
    막은 값을 오류 메시지로 되돌려 주는 셈이라 **방어가 자기 목적과 반대로 동작**한다 —
    SR-025 가 422 응답에서 `input` 을 지우며 닫은 것과 같은 패턴(CWE-209)이다.

    조용해지지는 않는다. 역할을 나눈다:
      · **운영자**  — 호출부의 `logger.exception` 이 예외 메시지 + 스택을 남긴다
                      (로그 마스킹 필터가 걸린 경로다).
      · **사용자**  — `verdict`("정비사업 판정 보류") · `rationale` · `missing` 으로
                      *판정을 못 냈다*는 사실을 보고, 결과 notes 에 건수도 적힌다.
    한 값이 두 독자를 겸하려다 금액이 샜다. 겸하지 않는다.
    """
    return RedevAssessment(
        available=False, stage=STAGE_UNKNOWN, raw_stage="", score=None, confidence=0.0,
        verdict="정비사업 판정 보류",
        rationale=COST_GUARD_DEGRADED_REASON,
        missing=(COST_GUARD_DEGRADED_REASON,),
        must_verify=("정비사업 여부·단계는 관할 구청 주거정비과 또는 정비사업 "
                     "정보몽땅에서 직접 확인하세요.",),
        detail={COST_GUARD_DETAIL_KEY: True},
    )


def redevelopment_assessment(candidate: Candidate, as_of: dt.date, *,
                             purpose: str = PURPOSE_LIVE) -> RedevAssessment:
    """이 후보의 정비사업 판정. 매칭된 구역이 없으면 '미확보' 판정을 낸다.

    ⚠️ **분담금 방어가 걸려도 추천을 죽이지 않는다** (CR31-1, 2026-07-28)
    -------------------------------------------------------------------
    `assert_no_cost_estimate` 는 개발자 문장에 대한 lint 다. 그런데 그 검사가 도는
    문장에는 수집 원문(구역명·원문 단계명)이 인용돼 있어서, 예전에는 `제3원구역`
    같은 값 하나로 `CostEstimateError` 가 나고 **아무도 잡지 않아 job 전체가
    'failed' + 빈 결과**가 됐다. 후보 한 건의 구역명 때문에 추천이 통째로 사라지는 것은
    lint 가 낼 수 있는 대가가 아니다.

    1차 방어는 도메인 쪽 `source_quotes`(인용문을 검사 대상에서 뺀다)이고, 여기는
    **그물**이다 — 새 필드를 문장에 끼우고 `_source_quotes` 갱신을 잊는 날을 대비한다.
    걸리면 그 후보의 재건축 블록만 '판정 보류'로 내려놓고, 왜 그랬는지 사유 문장과
    `logger.exception` 을 남긴다. 요약 한 줄 때문에 추천 전체를 날리지 않는다는
    `portfolio_summary` 의 원칙과 같은 판단이다.
    """
    try:
        return assess_redevelopment(candidate.redevelopment, purpose=purpose, as_of=as_of)
    except CostGuardError:
        # 원인(어떤 주제어·어떤 금액이 걸렸는가)이 남는 **유일한 자리**다 —
        # 응답에는 싣지 않는다(SR27-1). 스택까지 남겨 운영자가 코드 위치를 찾게 한다.
        # 여기 실리는 것은 구역명·단계명 같은 공개 수집값이지 사용자 자산이 아니다.
        logger.exception(
            "정비사업 판정이 분담금 검사에 걸려 이 후보만 판정 보류로 내립니다 "
            "(complex_id=%s)", candidate.complex_id)
        return _cost_guard_degraded()


def redevelopment_pair(candidate: Candidate, as_of: dt.date, *,
                       purpose: str = PURPOSE_LIVE
                       ) -> tuple[RedevAssessment, "Finding", bool]:
    """정비사업 판정 + Finding 을 **한 묶음으로** 만든다. 반환 3번째는 강등 여부.

    둘을 따로 만들면 판정은 통과했는데 Finding 변환에서 lint 가 걸리는 상태가 생기고,
    그러면 카드에는 재건축 블록이 있는데 findings 에는 없는 **반쪽 결과**가 나간다.
    한 자리에서 만들고, 걸리면 **둘 다** 판정 보류로 내린다.

    ⚠️ 강등 여부는 **판정 객체에서 읽는다**(`is_cost_guard_degraded`). 여기서 잡은
       예외만 세면, 한 단계 앞(`redevelopment_assessment`)에서 이미 잡아 강등한 건은
       **세어지지 않아 고지가 빠진다** — 조용한 강등이 되는 자리다.
    """
    assessment = redevelopment_assessment(candidate, as_of, purpose=purpose)
    try:
        return (assessment, redevelopment_finding(assessment),
                is_cost_guard_degraded(assessment))
    except CostGuardError:
        # 예외 문자열은 로그에만(SR27-1) — 카드에는 '판정 보류' 사실만 나간다.
        logger.exception(
            "정비사업 Finding 변환이 분담금 검사에 걸려 이 후보만 판정 보류로 내립니다 "
            "(complex_id=%s)", candidate.complex_id)
        degraded = _cost_guard_degraded()
        return degraded, redevelopment_finding(degraded), True


def redevelopment_finding(assessment: RedevAssessment) -> Finding:
    """판정 → Finding. 구역이 확인되지 않으면 **판단 보류**(0 점이 아니다)."""
    if not assessment.available:
        return insufficient(AGENT_REDEV, list(assessment.missing))

    # 이중 방어 — 도메인을 우회해 만들어진 문장이 섞여 들어올 여지를 남기지 않는다.
    # 검사 경계는 도메인과 **같아야 한다**: 수집 원문 인용분은 여기서도 뺀다.
    # (같은 문장을 여기서만 다른 기준으로 보면, 도메인을 통과한 판정이 여기서 죽는다.)
    assert_no_cost_estimate(assessment.rationale, assessment.verdict,
                            *(detail for _, detail in assessment.risks),
                            *assessment.upsides,
                            source_quotes=assessment.source_quotes)

    evidence = [Evidence(claim=e["claim"], source=e["source"], as_of=e.get("as_of"),
                         source_url=e.get("source_url"))
                for e in assessment.evidence]
    risks = [Risk(severity, detail) for severity, detail in assessment.risks]
    return validate_finding(Finding(
        agent_id=AGENT_REDEV,
        verdict=assessment.verdict,
        rationale=assessment.rationale,
        evidence=evidence,
        risks=risks,
        score=assessment.score,
        confidence=assessment.confidence,
        basis=assessment.basis,
        missing=list(assessment.missing),
    ))


def _redev_dict(assessment: RedevAssessment) -> dict[str, Any]:
    """추천 아이템에 실리는 정비사업 블록.

    점수만 주면 검증할 수 없다. **단계·원문 단계명·상방·하방·직접 확인할 것**을 함께 준다.
    """
    return {
        "available": assessment.available,
        "stage": assessment.stage,
        "raw_stage": assessment.raw_stage,
        "score": assessment.score,
        "confidence": assessment.confidence,
        "verdict": assessment.verdict,
        "early_stage": assessment.early_stage,
        "years_since_milestone": assessment.years_since_milestone,
        "supply_ratio": assessment.supply_ratio,
        "upsides": list(assessment.upsides),
        "risks": [{"severity": s, "detail": d} for s, d in assessment.risks],
        "must_verify": list(assessment.must_verify),
        "missing": list(assessment.missing),
        "detail": dict(assessment.detail),
    }


def avoids_early_redevelopment(avoid: dict[str, Any] | None) -> bool:
    """사용자가 '초기 단계 재건축'을 기피로 걸었나 (api-spec §2).

    문자열 'false'·'0' 을 참으로 읽지 않는다 — 기피 조건은 **후보를 지우는** 판정이라
    잘못 켜지면 사용자가 볼 수 있었던 집이 통째로 사라진다.
    """
    value = (avoid or {}).get(AVOID_REDEV_EARLY)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "no", "off")
    return bool(value)


# ---------------------------------------------------------------------------
# [4] portfolio-advisor — LLM 종합
# ---------------------------------------------------------------------------

# --- LLM 비용·지연 방어 ------------------------------------------------------
#
# 이 파이프라인은 **후보 1건마다** 요약 LLM 을 부른다. 후보 상한이 200 건이므로
# 아무 제한이 없으면 추천 한 번에 최대 200 회 호출이 나간다 — 그런데 사용자에게
# 실제로 보이는 것은 상위 `top_n`(기본 10) 뿐이고 나머지는 **만들자마자 버려진다.**
# 그래서 두 가지를 건다:
#   ① 요약은 **순위를 매긴 뒤 상위 후보에만** 만든다(아래 run_mvp_pipeline 2패스).
#   ② 그 위에 **호출 횟수 상한**을 둔다(top_n 이 50 이어도 여기서 멈춘다).
# 상한에 걸린 후보는 규칙 기반 요약을 받고, **그 사실을 notes 로 말한다**(조용히 줄이지 않는다).

#: 순위 확정 전까지 Finding 객체를 실어 나르는 **내부 전용** 키.
#: 밑줄로 시작해 응답 필드와 겹치지 않고, 요약 패스에서 pop 되어 절대 밖으로 나가지 않는다.
_SUMMARY_INPUT_KEY = "_summary_findings"

#: 추천 1건이 쓸 수 있는 LLM 요약 호출 수. `DEFAULT_TOP_N` 과 같은 값으로 둔다 —
#: 기본 요청(top_n=10)은 전부 LLM 요약을 받고, 더 큰 top_n 만 상한에 걸린다.
LLM_SUMMARY_LIMIT = 10
#: 연속 실패 임계. 이만큼 실패하면 남은 후보는 시도조차 하지 않는다(회로 차단).
#: 장애는 보통 전면적이라, 계속 시도하면 후보 수만큼 타임아웃을 곱하게 된다.
LLM_MAX_FAILURES = 2


@dataclass
class LLMBudget:
    """추천 1건의 LLM 사용 한도와 **실제 사용 내역**.

    한도만 두고 끝내지 않고 무엇이 왜 규칙 기반으로 떨어졌는지 세어 둔다 —
    그래야 결과 `notes` 로 사용자에게 말할 수 있다. 세지 않으면 "AI 추천"을 눌렀는데
    규칙 기반 문장이 나온 이유를 아무도 설명할 수 없다.
    """

    max_calls: int = LLM_SUMMARY_LIMIT
    max_failures: int = LLM_MAX_FAILURES
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_prompt_chars: int = MAX_PROMPT_CHARS

    calls: int = 0                  #: 실제로 나간 호출 수
    failures: int = 0               #: 실패(타임아웃·429·5xx·스키마 위반) 수
    over_budget: int = 0            #: 호출 상한에 걸려 시도조차 못 한 후보 수
    circuit_open: int = 0           #: 연속 실패로 차단된 뒤 건너뛴 후보 수
    oversized: int = 0              #: 프롬프트가 길이 상한을 넘어 폐기한 후보 수
    #: 응답이 **분담금 주제**를 건드려 폐기한 후보 수 (SR24-3 / CR-029·CR-030 차단 1).
    #: `failures` 와 따로 센다 — 이건 장애가 아니라 **내용 위반**이라 회로를 열면 안 된다
    #: (한 후보의 문장이 규칙을 어겼다고 남은 후보의 요약까지 끊을 이유가 없다).
    cost_blocked: int = 0

    @property
    def tripped(self) -> bool:
        """회로가 열렸나(= 이번 job 에서 LLM 을 더 이상 시도하지 않는다)."""
        return self.failures >= self.max_failures

    def take(self) -> bool:
        """호출 슬롯 하나를 확보한다. 못 얻으면 사유를 세고 False."""
        if self.tripped:
            self.circuit_open += 1
            return False
        if self.calls >= self.max_calls:
            self.over_budget += 1
            return False
        self.calls += 1
        return True


#: 키가 없어 규칙 기반으로 돈 경우. **"AI 추천"을 눌렀는데 LLM 이 안 돌았다는 사실을
#: 사용자가 알 길이 없는 상태**를 막는다. 순위·근거는 LLM 과 무관하다는 점도 함께 말한다
#: (그래야 "그럼 이 결과는 못 믿나"로 오해하지 않는다).
NOTE_LLM_DISABLED = (
    "요약 문장은 규칙 기반으로 생성했습니다(AI 미연결 — ANTHROPIC_API_KEY 미설정). "
    "추천 순위·가격 근거·제외 사유는 규칙과 실거래 통계로 계산하므로 AI 연결 여부와 무관합니다."
)
NOTE_LLM_FAILED = (
    "AI 요약 호출이 실패해 {n}건은 규칙 기반 요약으로 대체했습니다. "
    "추천 순위와 근거 자체는 영향받지 않습니다."
)
NOTE_LLM_BUDGET = (
    "비용 상한(추천 1건당 AI 요약 {limit}회)에 걸려 {n}건은 규칙 기반 요약입니다."
)
NOTE_LLM_OVERSIZED = (
    "근거가 많아 프롬프트 길이 상한을 넘은 {n}건은 규칙 기반 요약입니다"
    "(근거를 잘라서 요약하지 않습니다)."
)
#: ★ 조용히 바꾸지 않는다. AI 요약이 **주지도 않은 주제**(추가분담금)를 꺼냈다는 것은
#: 사용자가 알아야 하는 사실이다 — 문장만 슬쩍 규칙 기반으로 바꾸고 넘어가면,
#: "AI 가 분담금을 말하려 했다"는 신호가 아무 데도 안 남는다.
#:
#: ⚠️ 이 문장은 **실제로 하는 일만** 적는다(CR30-1). 예전 문구는 두 군데가 거짓이었다:
#:   ① 폐기 사유를 "금액을 언급해서"라고 단정했지만, 지금 기준은 **주제어**다
#:      (금액이 없는 언급도 폐기한다 — 재료를 준 적이 없으므로).
#:   ② "어떤 경로로도 그 금액을 제시하지 않습니다"는 **지킬 수 없는 약속**이었다.
#:      주제어 없이 금액만 쓰는 문장은 텍스트 검사로 잡히지 않는다. 그래서 쓰지 않는다.
NOTE_LLM_COST_BLOCKED = (
    "AI 요약 {n}건이 추가분담금·부담 관련 표현을 써서 폐기하고 규칙 기반 요약으로 "
    "대체했습니다(금액 여부와 무관하게 폐기합니다). 분담금 자료는 공개 데이터에 없어 "
    "AI 에게 전달하지도, 분석에 반영하지도 않았습니다 — 규모는 조합 사무실·"
    "정비사업 정보몽땅에서 직접 확인하세요."
)


def llm_notes(budget: LLMBudget | None, *, llm_connected: bool) -> list[str]:
    """LLM 사용 내역 → 사용자에게 보일 고지 문장."""
    if not llm_connected:
        return [NOTE_LLM_DISABLED]
    if budget is None:
        return []
    out: list[str] = []
    if budget.failures:
        out.append(NOTE_LLM_FAILED.format(n=budget.failures + budget.circuit_open))
    if budget.over_budget:
        out.append(NOTE_LLM_BUDGET.format(limit=budget.max_calls, n=budget.over_budget))
    if budget.oversized:
        out.append(NOTE_LLM_OVERSIZED.format(n=budget.oversized))
    if budget.cost_blocked:
        out.append(NOTE_LLM_COST_BLOCKED.format(n=budget.cost_blocked))
    return out


PORTFOLIO_SYSTEM = """당신은 부동산 분석 결과를 요약하는 역할입니다.

절대 규칙:
1. 제공된 분석 결과에 **없는 사실을 추가하지 마세요.**
2. 각 문장은 제공된 evidence 중 하나에 대응해야 합니다.
3. 미래 가격 상승을 단정하지 마세요. "오릅니다" 같은 표현 금지.
4. 투자를 권유하는 표현을 쓰지 마세요.
5. 확신할 수 없으면 "확인 필요"라고 쓰세요.
6. 단점(why_not)을 반드시 포함하세요. 장점만 나열하면 안 됩니다.
7. **'분담'·'부담'·'환급'·'추가 비용' 이라는 낱말을 아예 쓰지 마세요.**
   조합 내부 자료라 공개 데이터에 없고, 위 분석 결과에도 **한 줄도 들어 있지 않습니다.**
   이 주제의 안내("조합에서 직접 확인하세요")는 시스템이 고정 문구로 따로 붙이므로
   당신이 쓸 필요가 없습니다. 이 낱말이 하나라도 들어가면 **요약 전체가 폐기되고**
   규칙 기반 문장으로 대체됩니다 — 금액을 썼는지 여부와 무관합니다.
   세대수·연도·거리·면적·가격은 **분석 결과에 있는 값이면** 숫자로 써도 됩니다.

JSON 으로만 답하세요:
{"headline": "한 줄 요약", "why": ["근거1","근거2"], "why_not": ["리스크1"],
 "next_actions": ["현장에서 확인할 것"]}"""


def _fallback_summary(findings: list[Finding]) -> dict[str, Any]:
    """LLM 이 실패해도 제품이 죽지 않게 규칙 기반으로 요약한다.

    문장은 투박하지만 **근거는 정확하다.** 그럴듯한 문장보다 정확한 근거가 낫다.
    """
    why = [f.rationale for f in findings if not f.missing and f.rationale]
    why_not = [r.detail for f in findings for r in f.risks]
    return {
        "headline": "분석 요약(자동 생성)",
        "why": why[:5],
        "why_not": why_not[:5] or ["확인된 하방 리스크 없음 — 데이터 부족일 수 있습니다."],
        "next_actions": ["현장 방문으로 소음·일조·주차 확인",
                         "등기부등본으로 권리관계 확인(본 시스템은 확인하지 않음)"],
        "generated_by": "fallback",
    }


def _cost_free_finding(finding: Finding) -> dict[str, Any]:
    """LLM 프롬프트에 실을 finding — **분담금 주제 문장을 빼고** 넘긴다.

    `Finding.to_dict()` 의 텍스트 필드를 **하나씩 명시적으로** 훑는다. 재귀 순회로
    "문자열이면 무조건" 처리하지 않는 이유는, 나중에 텍스트 필드가 늘었을 때 조용히
    통과시키는 것보다 **눈에 띄게 빠뜨리는 편이 낫기 때문**이다 — 빠뜨리면 호출부의
    `contains_cost_topic(user)` fail-safe 가 잡아 호출 자체를 막는다.

    ⚠️ 이 함수는 **프롬프트 전용**이다. 카드에 실리는 `findings`(응답)에는 원문이
       그대로 남는다 — 사용자에게는 분담금 고지가 **보여야** 한다.
    """
    d = finding.to_dict()
    d["verdict"] = redact_cost_topic(d.get("verdict"))
    d["rationale"] = redact_cost_topic(d.get("rationale"))
    d["missing"] = [t for t in (redact_cost_topic(m) for m in d.get("missing") or []) if t]
    d["risks"] = [r for r in ({**r, "detail": redact_cost_topic(r.get("detail"))}
                              for r in d.get("risks") or []) if r["detail"]]
    d["evidence"] = [e for e in ({**e, "claim": redact_cost_topic(e.get("claim"))}
                                 for e in d.get("evidence") or []) if e["claim"]]
    return d


def portfolio_summary(findings: list[Finding], llm: LLMClient | None,
                      forbidden_amounts: list[int], *,
                      budget: LLMBudget | None = None) -> dict[str, Any]:
    """근거를 요약 문장으로. **실패·상한은 전부 규칙 기반으로 폴백**한다.

    LLM 이 죽어도 추천은 나온다 — 순위·가격 근거·제외 사유는 이미 규칙과 통계로
    계산돼 있고, 여기서 하는 일은 그것을 문장으로 옮기는 것뿐이다.
    다만 **폴백했다는 사실은 세어서(`budget`) 결과 notes 로 말한다**(조용히 바꾸지 않는다).
    """
    if llm is None:
        # 외부 전송이 없다 → tripwire 불필요(구조적 방어만으로 충분).
        return _fallback_summary(findings)

    # fail-loud: 실제 외부(LLM) 전송 경로인데 tripwire 검사값이 하나도 없으면
    # "검사할 게 없어서 통과"라는 조용한 no-op 을 만들지 않고 **막는다**.
    # (best-effort 그물이라도 실경로에서 무장 해제된 채 나가지 않게 강제)
    if not [v for v in forbidden_amounts if v and v >= 1_000_000]:
        raise PromptSafetyError(
            "forbidden_amounts 가 비어 자산유출 tripwire 가 무장 해제됩니다. "
            "affordability 원본에서 파생한 검사값을 넘기세요. (security.md §6)"
        )

    # ★ CR30-1 — **분담금 주제를 모델에게서 빼앗는다.**
    #
    # 예전에는 `COST_DISCLOSURE`("추가분담금은 조합 내부 자료라 확인할 수 없어…")를
    # rationale 에 실어 보내면서 세대수 증감을 함께 줬다. 모델이 분담금을 말한 것은
    # 우리가 시켰기 때문이다 — 그리고 그 뒤에 정규식으로 금액을 쫓았다. 표기 변형이
    # 무한하므로 그 싸움은 이길 수 없다(문장 분리·거리·어간·필드 분리로 4종이 뚫렸다).
    #
    # 그래서 재료를 뺀다. 고지는 **LLM 출력과 무관하게** 코드가 붙인다:
    #   · `_merge_actions` 가 `must_verify`(1번이 분담금 직접확인)를 next_actions 맨 앞에
    #   · `run_mvp_pipeline` 이 결과 notes 에 고정 문장
    #   · `scoring.summary_notes` 의 coverage_gap
    # 잃는 정보가 없고, 대신 **출력에 주제어가 보이는 것 자체가 이상 신호**가 된다.
    payload = [_cost_free_finding(f) for f in findings]
    user = data_block("analysis_results", payload) + \
        "\n\n위 분석 결과만으로 요약하세요. 없는 사실을 만들지 마세요."

    # fail-safe: 위 정리를 빠져나간 분담금 문구가 하나라도 남아 있으면 **보내지 않는다.**
    # (미래에 Finding 에 새 텍스트 필드가 생기고 `_cost_free_finding` 을 갱신하지 않으면
    #  여기서 걸린다 — 조용히 재료가 되살아나는 것을 막는 구조적 문이다.)
    if contains_cost_topic(user):
        logger.error("프롬프트에 분담금 재료가 남아 LLM 호출을 건너뜁니다"
                     " — _cost_free_finding 갱신 필요")
        return _fallback_summary(findings)

    # 자산 원본 금액이 섞였는지 호출 직전에 걸러낸다 (best-effort tripwire, security.md §6).
    # ⚠️ 주 방어는 이게 아니라 finding 이 파생값만 싣는 구조다.
    # ⚠️ 이 검사는 **호출 상한·회로 차단보다 먼저** 돈다. 예산이 없다는 이유로 tripwire 를
    #    건너뛰면, 상한에 걸린 날에만 검사가 사라지는 셈이 된다(그런 방어는 방어가 아니다).
    assert_no_secrets(user, forbidden_amounts)

    for hit in scan_injection(user):
        logger.warning("수집 데이터에서 인젝션 의심 패턴 발견: %s", hit)

    if budget is not None:
        limit = budget.max_prompt_chars
        if len(user) + len(PORTFOLIO_SYSTEM) > limit:
            # 자르지 않는다 — 근거 일부만 보고 쓴 요약은 근거와 어긋난다(G2).
            budget.oversized += 1
            logger.warning("프롬프트가 상한(%d자)을 넘어 규칙 기반으로 대체합니다", limit)
            return _fallback_summary(findings)
        if not budget.take():
            return _fallback_summary(findings)

    max_tokens = budget.max_tokens if budget is not None else DEFAULT_MAX_TOKENS
    try:
        raw = llm.complete_json(system=PORTFOLIO_SYSTEM, user=user,
                                max_tokens=max_tokens)
    except LLMError as exc:
        # ⚠️ 예외 문자열에 프롬프트·키가 없다는 전제는 llm.py 가 지킨다(상태코드만 남긴다).
        logger.warning("LLM 요약 실패, 규칙 기반으로 대체합니다: %s", exc)
        if budget is not None:
            budget.failures += 1
        return _fallback_summary(findings)

    # 스키마 검증 — 벗어나면 폐기하고 폴백
    if not isinstance(raw.get("headline"), str) or not isinstance(raw.get("why"), list):
        logger.warning("LLM 응답이 스키마를 벗어나 폐기합니다")
        if budget is not None:
            budget.failures += 1
        return _fallback_summary(findings)

    why_not = raw.get("why_not")
    if not isinstance(why_not, list) or not why_not:
        # 단점을 안 쓰면 우리가 채운다. 장점만 있는 리포트는 내보내지 않는다.
        why_not = [r.detail for f in findings for r in f.risks] or \
            ["확인된 하방 리스크 없음 — 데이터 부족일 수 있습니다."]

    summary = {
        "headline": raw["headline"],
        "why": [str(x) for x in raw["why"]][:6],
        "why_not": [str(x) for x in why_not][:6],
        "next_actions": [str(x) for x in (raw.get("next_actions") or [])][:5],
        "generated_by": "llm",
    }

    # ★ 마지막 문(SR24-3 / CR-029·CR-030 차단 1) — **카드에 찍히는 문자열**을 검사한다.
    #
    # 카드의 headline·why·why_not·next_actions 는 도메인이 아니라 **여기 LLM 출력**이
    # 만든다. 그 경로에 검사가 없어서 "추가분담금 약 1.2억 원 예상"이 사용자 카드까지
    # 도달했고(CR-029), 금액 근접 정규식으로 막았더니 문장 분리·거리·어간·필드 분리로
    # 다시 뚫렸다(CR-030). 그래서 **금액을 찾는 것을 그만뒀다.**
    #
    # 지금 기준은 한 가지다 — **분담금 주제어가 보이면 폐기.**
    #   · 위에서 재료를 뺐으므로 모델이 이 주제를 꺼낼 근거가 없다 → 나오면 지어낸 것이다.
    #   · 금액 표기 변형을 쫓지 않으므로 "다음 변형"이 없다.
    #   · 옳은 문장("확인되지 않았습니다")이 걸려도 **잃는 정보가 0**이다 —
    #     같은 내용을 코드가 고정 문장으로 이미 말한다(`_merge_actions` · notes).
    #
    # ⚠️ 예외로 죽이지 않는다. 요약 한 줄 때문에 추천 전체(순위·가격 근거·제외 사유)를
    #    날리는 것은 과하다. 대신 규칙 기반 요약으로 **강등**하고, 강등했다는 사실을
    #    센다(`budget.cost_blocked` → `NOTE_LLM_COST_BLOCKED`). 조용히 바꾸지 않는다.
    try:
        assert_no_cost_topic(summary["headline"], *summary["why"],
                             *summary["why_not"], *summary["next_actions"])
    except CostGuardError as exc:
        # 적발 문구는 남긴다(운영자가 어떤 모델이 무슨 문장을 뱉었는지 알아야 고친다).
        # 사용자 자산·소득이 아니라 **모델이 지어낸 문장**이라 마스킹 대상이 아니다.
        logger.warning("AI 요약이 분담금 주제를 건드려 규칙 기반으로 대체합니다: %s", exc)
        if budget is not None:
            budget.cost_blocked += 1
        return _fallback_summary(findings)

    return summary


# ---------------------------------------------------------------------------
# 파이프라인
# ---------------------------------------------------------------------------

def _avoid_tokens(avoid: dict[str, Any] | None) -> list[str]:
    """느슨하게 들어오는 기피 조건에서 문자열 토큰만 긁어낸다.

    입지와 무관한 토큰(1층·재건축 등)은 하위 로직(``_canonical_avoids``)이 걸러낸다.

    ⚠️ **꺼진 조건(False·빈 값)은 토큰이 아니다** (2026-07-27 수정). 화면은 체크를 풀면
    `{"main_road_noise": false}` 를 그대로 저장한다 — 예전에는 값과 무관하게 키를
    실어서, 사용자가 **체크를 해제한 기피 조건이 계속 적용됐다.** 조건을 껐는데
    결과가 그대로인 형태라 원인을 짐작할 수도 없다(이 프로젝트가 경계하는 조용한 실패).
    """
    tokens: list[str] = []
    for key, val in (avoid or {}).items():
        if val is None or val is False:
            continue
        if isinstance(val, (list, tuple, set)) and not val:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        tokens.append(str(key))
        if isinstance(val, str):
            tokens.append(val)
        elif isinstance(val, (list, tuple, set)):
            tokens += [str(x) for x in val]
    return tokens


def excluded_record(*, complex_id: int | None, complex_name: str | None,
                    area_m2: float | None, price_basis: str | None,
                    code: str, reason: str) -> dict[str, Any]:
    """제외된 후보 1건의 **표준 모양**. 만드는 자리가 여럿이라 한 곳에 모아 둔다.

    `complex_id` 만 남기면 화면은 "단지 #2048 제외"라고 밖에 못 쓰고, 그건 사용자에게
    아무 답도 아니다("내가 아는 그 단지가 이건가?"). 단지명·면적·가격 근거를 같이 준다.

    `reason_code` 는 기계가 읽는 축이다. 사유 문장에는 단지 사정(금액·표본 수)이 섞여
    들어가 그대로 세면 전부 유니크해진다 — 사유별 분포를 내려면 코드가 필요하다.
    문장(`reason`)은 사람용, 코드는 집계용이고 **둘 다 남긴다**.
    """
    return {
        "complex_id": complex_id,
        "complex_name": complex_name,
        "area_m2": area_m2,
        "price_basis": price_basis,
        "price_estimated": (None if price_basis is None
                            else price_basis != PRICE_BASIS_LISTING),
        "reason_code": code,
        "reason": reason,
    }


def excluded_entry(cand: Candidate, *, code: str, reason: str) -> dict[str, Any]:
    """후보(Candidate)에서 제외 항목을 만든다."""
    return excluded_record(
        complex_id=cand.complex_id, complex_name=cand.complex_name,
        area_m2=cand.area_m2, price_basis=cand.price_basis,
        code=code, reason=reason)


def _rank_cutoff_entry(item: dict[str, Any], top_n: int) -> dict[str, Any]:
    """순위에서 잘린 후보 1건. 제외 사유 목록과 **같은 모양**으로 만든다.

    점수가 없으면(`total_score is None`) "0점이라 밀렸다"가 아니라 **점수를 매길 근거가
    없어서** 뒤로 간 것이다 — 그 차이를 문장에 그대로 적는다(0 과 null 을 섞지 않는다).
    """
    score = item.get("total_score")
    tail = (f"점수 {score}" if score is not None
            else "점수를 매길 근거(호가 갭·입지 실측)가 없어 뒤로 밀림")
    entry = excluded_record(
        complex_id=(item.get("complex") or {}).get("id"),
        complex_name=(item.get("complex") or {}).get("name"),
        area_m2=(item.get("unit_type") or {}).get("area_m2"),
        price_basis=item.get("price_basis"),
        code=EXCLUDED_RANK_CUTOFF,
        reason=f"상위 {top_n}건 밖 — {tail}")
    entry["total_score"] = score
    return entry


#: 카드 하나에 실을 '직접 확인할 것' 최대 개수. 너무 길면 아무도 안 읽는다.
_MAX_ACTIONS = 6


def _merge_actions(summary_actions: list[str], must_verify: list[str]) -> list[str]:
    """요약이 만든 액션 + **시스템이 확인해 주지 못하는 것**을 합친다.

    ⚠️ `must_verify` 를 앞에 둔다. LLM 이 쓴 일반적인 조언보다 "추가분담금은 우리가
    확인해 주지 않는다"가 먼저 읽혀야 한다 — 그걸 확인했다고 믿는 순간이 가장 위험하다.
    """
    out: list[str] = []
    for item in list(must_verify) + list(summary_actions):
        if item and item not in out:
            out.append(item)
    return out[:_MAX_ACTIONS]


#: 시점 보정 고지 문구. **"현재 시세"라는 말을 쓰지 않는다** — 기준월은 완결된 가장
#: 최근 달이고(신고 지연 때문에 이번 달은 표본이 덜 찼다), 그 사실이 사용자가 이 숫자를
#: 얼마나 믿을지 정하는 근거다(timeadjust 규칙 3).
NOTE_TIME_ADJUSTED = (
    "적정가 밴드는 {yms} 시점으로 환산했습니다({n}건) — 6~36개월 거래를 그대로 섞으면 "
    "창의 중간 시점 가격이 되어 상승장에서 낮게 나오기 때문입니다"
    "(자체 시장지수, 국토교통부 실거래가 기반). 그 시점 이후의 실제 거래가는 다를 수 있습니다."
)
#: ★ 조용히 넘어가면 안 되는 쪽. 보정을 **시도했는데 못 한** 후보가 있으면 반드시 말한다.
NOTE_TIME_NOT_ADJUSTED = (
    "추천 {n}건은 시점 보정을 적용하지 못해 최근 6~36개월 거래를 시점 구분 없이 섞은 "
    "적정가입니다(사유: {reasons}). 상승장에서는 실제 시세보다 낮게 나오며, 호가가 없는 "
    "후보에서는 이 값이 예산 판정 기준가라 **살 수 없는 후보가 예산 안으로 통과**할 수 있습니다."
)
#: 배선 자체가 꺼진 경우(지수 조회를 하지 않음). 운영에서는 이 문장이 보이면 안 된다.
NOTE_TIME_NOT_ATTEMPTED = (
    "적정가 밴드에 시점 보정을 적용하지 않았습니다(시장지수 미조회). 6~36개월 거래를 "
    "시점 구분 없이 섞은 값이라 어느 시점의 가격도 아닙니다."
)


def time_adjust_notes(items: list[dict[str, Any]], *, attempted: bool) -> list[str]:
    """시점 보정이 **실제로 걸렸는지**를 결과 상단에서 말한다.

    왜 카드 안(`price_band.time_adjustment`)만으로 부족한가 — 사용자는 카드를 하나씩
    열어 보지 않는다. 그리고 이 보정은 **가격의 의미 자체**를 바꾼다(체결가 혼합 →
    특정 시점 환산). 어느 쪽인지 모르면 두 값을 같은 잣대로 비교하게 된다.
    """
    bands = [it.get("price_band") for it in items if it.get("price_band")]
    if not bands:
        return []
    if not attempted:
        return [NOTE_TIME_NOT_ATTEMPTED]

    done = [b for b in bands if b.get("time_adjusted")]
    missed = [b for b in bands if not b.get("time_adjusted")]
    out: list[str] = []
    if done:
        yms = sorted({b["as_of_ym"] for b in done if b.get("as_of_ym")})
        out.append(NOTE_TIME_ADJUSTED.format(yms="·".join(yms), n=len(done)))
    if missed:
        reasons = sorted({(b.get("time_adjustment") or {}).get("reason") or "사유 미상"
                          for b in missed})
        out.append(NOTE_TIME_NOT_ADJUSTED.format(n=len(missed),
                                                 reasons="; ".join(reasons)))
    return out


def _derive_forbidden(ctx: AnalysisContext) -> list[int]:
    """tripwire 검사값을 방어적으로 보강한다.

    호출자가 `forbidden_amounts` 를 채워 넘기지 않아도(A5) affordability 파생값 중
    **원본에 가까운 값**을 자동으로 포함시켜, 실경로에서 tripwire 가 완전 no-op 이 되지 않게 한다.
    (income·기존대출 원본은 AffordabilityResult 에 남지 않으므로, 그건 호출자가 넘겨야 하고
     안 넘기면 `portfolio_summary` 의 fail-loud 가 막는다.)
    """
    vals: set[int] = {v for v in ctx.forbidden_amounts if v}
    usable_cash = getattr(ctx.affordability, "usable_cash_krw", 0)
    if usable_cash:
        vals.add(usable_cash)
    return sorted(vals)


def run_mvp_pipeline(ctx: AnalysisContext, *, llm: LLMClient | None = None,
                     top_n: int = 10) -> dict[str, Any]:
    """MVP 5종 파이프라인 실행.

    반환
    ----
    ``items``     상위 top_n 추천(순위 부여)
    ``excluded``  **나머지 전부** — 하드 제외(가격근거·예산·기피) + 순위 컷.
                  ``len(items) + len(excluded) == len(ctx.candidates)`` 가 성립한다.
                  이 등식이 깨지면 어딘가에서 후보가 **말없이 사라진 것**이다.
    ``notes``     결과 전체에 붙는 단서
    """
    finance = finance_finding(ctx.affordability)
    # 희망 매매가가 있으면 그것이 상한이고, 없으면 최대 실구매 가능 금액이다.
    # (예전엔 후자로 고정돼 있어 `budget_override_krw` 가 제외 판정에 닿지 못했다.)
    # ⚠️ 상한은 **후보마다 그 후보의 면적으로** 세운다(`ctx.budget_cap_krw` — CR39-2).
    #    한 숫자로 전부를 판정하면 85㎡ 를 가로지르는 목록에서 반드시 갈리고, 방향이
    #    관대해서 **못 사는 후보가 통과**한다. 희망 매매가 기준이면 면적과 무관한 금액
    #    하나라 후보마다 같은 값이 나온다(그때는 예전과 결과가 같다).
    avoid_tokens = _avoid_tokens(ctx.avoid)
    forbidden = _derive_forbidden(ctx)
    # 저장된 가중치는 **클라이언트의 주장**이다. 여기서 다시 정규화하고,
    # 모르는 키는 버리되 목록으로 받아 notes 에 남긴다(조용히 버리지 않는다).
    weights, unknown_weight_keys = normalize_weights(ctx.weights)
    # 사용자가 준 적 없어 기본값이 들어간 축(재건축). notes 로 반드시 말한다.
    defaulted = defaulted_axes(ctx.weights)
    avoid_early_redev = avoids_early_redevelopment(ctx.avoid)

    items: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    scores: list[ScoreResult] = []  # 결과 전체 고지를 만들 때 다시 훑는다
    #: 분담금 방어에 걸려 재건축 블록만 내려놓은 후보 수. **0 이 아니면 반드시 말한다** —
    #: 조용히 '미확보'로 섞이면 수집 범위 밖(경기도)과 구분되지 않는다.
    cost_guard_degraded = 0
    #: 전용면적을 몰라 **예산 상한을 세우지 못한** 후보 수(자산 기준일 때만 생긴다).
    #: 제외하지도, 판정하지도 않고 통과시킨 후보다 — **0 이 아니면 반드시 말한다.**
    #: 말하지 않으면 사용자는 그 후보가 예산 안이라고 읽는다(조용한 통과도 조용한 실패다).
    budget_unknown_area = 0

    for cand in ctx.candidates:
        rep = cand.group.representative if cand.group is not None else None
        basis = cand.price_basis

        # 가격 근거를 먼저 확정한다. 호가가 있으면 호가(사실), 없으면 실거래 중위(추정).
        # 밴드는 여기서 한 번만 계산해 valuation 에 넘긴다(같은 숫자를 두 번 만들지 않는다).
        # ⚠️ 지수는 **루프 밖에서 이미 조회돼** 있다(ctx.market_indexes) — 여기서 DB 를
        #    때리지 않는다. 시점 보정이 붙으면 아래 `price` 가 곧 예산 판정 기준가라
        #    보정 여부가 **후보의 통과/제외를 바꾼다**(그게 이 배선의 목적이다).
        band = reference_band(cand, ctx.as_of, indexes=ctx.market_indexes)
        price = reference_price_krw(cand, band)

        # 하드 제외 ⓪ — 가격 근거가 아예 없다(호가 없음 + 실거래 표본 부족).
        # 예산을 따질 수도, 적정가를 말할 수도 없다. 지어내지 않고 사유를 남긴다.
        if price is None:
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_NO_PRICE,
                reason=("가격 근거 없음 — 활성 호가가 없고 "
                        + (band.reason or "실거래 표본 부족"))))
            continue

        # 하드 제외 ① — 아무리 점수가 높아도 못 사는 집은 추천이 아니다.
        # ⚠️ 실거래 기준이면 비교값이 **추정치**다. 사유 문구에 그 사실을 남긴다.
        # ⚠️ 상한은 **이 후보의 면적**으로 세운다(CR39-2). 사유 문장에 적히는 한도도
        #    판정에 실제로 쓴 그 숫자다 — 다른 숫자를 적으면 사용자가 되짚을 수 없다.
        cap = ctx.budget_cap_krw(cand.area_m2)
        if cap is None:
            # 면적을 몰라 세율 구간을 고를 수 없다 → **판정하지 않는다.**
            # 84 를 가정하면 *다른 면적의 한도*로 이 후보를 판정하는 것이고(CR37-1 의
            # 본체), 그렇다고 제외하면 "판정 못 함"을 "못 산다"로 바꾸는 것이다.
            # 그래서 통과시키되 **세어서 결과 고지로 말한다**(조용히 통과시키지 않는다).
            budget_unknown_area += 1
        elif cap and price > cap:
            # 실거래 기준이면 **어느 시점의 추정치인지**까지 적는다. 보정된 값을
            # 그냥 "최근 실거래 중위"라고 부르면 사용자가 원본 체결가로 읽는다.
            trade_label = (f"{band.as_of_label} 시점 환산 중위 {price:,}원(추정)"
                           if band.as_of_label else f"최근 실거래 중위 {price:,}원(추정)")
            label = (f"호가 {price:,}원" if basis == PRICE_BASIS_LISTING
                     else trade_label)
            # ⚠️ 여기 적히는 금액은 **후보 가격**과 **예산 한도(파생값)** 뿐이다.
            #    보유현금·연소득 원본을 문장에 넣지 않는다(SR4-2).
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_OVER_BUDGET,
                reason=f"예산 초과 ({label} > 한도 {cap:,}원)"))
            continue

        # 하드 제외 ② — 기피 조건은 가점 상쇄가 아니라 제외다(F5).
        loc_assess = (evaluate_location(cand.location, avoid=avoid_tokens, as_of=ctx.as_of)
                      if cand.location is not None else None)
        if loc_assess is not None and loc_assess.excluded:
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_AVOIDED,
                reason="; ".join(loc_assess.exclusion_reasons)))
            continue

        # 정비사업 판정은 **제외 판정보다 먼저** 필요하다(초기 단계 기피가 여기서 걸린다).
        # 판정과 Finding 을 한 번에 만든다 — 분담금 방어가 걸리면 **이 후보의 재건축
        # 블록만** 판정 보류로 내려가고(available=False), 추천 자체는 계속된다(CR31-1).
        redev_assess, redev_f, redev_blocked = redevelopment_pair(
            cand, ctx.as_of, purpose=ctx.purpose)
        if redev_blocked:
            cost_guard_degraded += 1

        # 하드 제외 ③ — '초기 단계 재건축 기피'(api-spec §2). 감점이 아니라 제외다.
        # ⚠️ **확인된 초기 단계일 때만** 뺀다. 정보가 없는 단지를 "초기일지도 모르니"
        #    빼면, 수집이 안 된 경기도 단지가 통째로 사라진다(모름 ≠ 해당).
        if avoid_early_redev and redev_assess.available and redev_assess.early_stage:
            excluded.append(excluded_entry(
                cand, code=EXCLUDED_AVOIDED,
                reason=(f"기피 조건(초기 단계 재건축) — {redev_assess.detail.get('zone_name')} "
                        f"구역이 {redev_assess.detail.get('stage_label')} 단계입니다")))
            continue

        # 환금성은 여기서 한 번 계산해 finding(문구)과 가치 축 점수가 같은 값을 보게 한다.
        liq = candidate_liquidity(cand, ctx.as_of)
        valuation = valuation_finding(cand, ctx.as_of, band=band, liq=liq)
        median = band.median_krw if band.available else None
        dong_val = None
        if band.available:
            # 밴드 기간이 아니라 dong_effect 자체 창을 쓴다(위 valuation_finding 주석 참조).
            # 실거래 기반이라 **호가 유무와 무관하게** 계산된다(F4 회귀 금지).
            dong_val = dong_effect(cand.trades, area_m2=cand.area_m2, as_of=ctx.as_of)

        location = (_assessment_to_finding(loc_assess) if loc_assess is not None
                    else insufficient("location-analyst",
                                      ["입지 데이터(학군·교통·인프라) 미수집"]))
        listing_f = listing_finding(cand, median, ctx.as_of)
        findings = [finance, listing_f, valuation, location, redev_f]

        # 총점: 사용자 가중치(가격·입지·가치·리스크·재건축)를 실제로 곱한다.
        # 근거 없는 축은 **총점에서 빼고 재정규화**하되 무엇이 빠졌는지 응답에 남긴다.
        # 점수를 매길 근거가 하나도 없으면 **0 이 아니라 None** 이다.
        # 0.0 은 "나쁘다"로 읽힌다 — "모른다"와 구분되지 않으면 그것도 환각이다(G2).
        signals = build_axis_signals(
            valuation=valuation, listing=listing_f, location=location,
            liq=liq, has_ask=cand.ask_price_krw is not None, redevelopment=redev_f)
        score = score_item(findings=findings, signals=signals, weights=weights)
        scores.append(score)

        items.append({
            "complex": {"id": cand.complex_id, "name": cand.complex_name},
            "unit_type": {"area_m2": cand.area_m2},
            # --- 화면 배지용 **값** (판정이 아니다) ----------------------------
            # total_households: 모르면 **null**. 0·false 로 만들지 않는다 —
            #   16,462개 중 2,666개가 미확보이고 "모름"과 "아님"은 다르다.
            # nearest_station: 입지 분석이 이미 잰 최근접 역 거리(직선, m).
            #   임계값 판정(1,000세대·500m)은 표시 계층이 한다(_nearest_station_dict 주석).
            "total_households": cand.total_households,
            "nearest_station": _nearest_station_dict(loc_assess),
            # 특정 매물의 동은 호가 표기 기준(추정) — confidence 를 낮게 실어 보낸다.
            # 호가가 없으면 특정 물건이 없으므로 building 도 없다(추정하지 않는다).
            "building": ({"id": rep.building_id, "confidence": 0.6,
                          "basis": "listing_reported"}
                         if rep is not None and rep.building_id else None),
            # F4 동별 가치 차이: aptDong 실거래 실측(basis=trade_measured, 높은 신뢰)
            # 이거나, 표본/동정보 부족 시 폴백을 명시한다. 없는 걸 지어내지 않는다.
            "dong_valuation": _dong_valuation_dict(dong_val),
            # 재건축·재개발 진행 단계와 그 **양면**(상방/하방) + 직접 확인할 것.
            # available=false 는 '정비사업 없음'이 아니라 '확인되지 않음'이다.
            "redevelopment": _redev_dict(redev_assess),
            # --- 가격 계약 (프론트가 반드시 구분해 표시해야 하는 부분) --------
            # price_basis="listing" → est_price_krw == ask_price_krw (지금 살 수 있는 값)
            # price_basis="trade"   → ask_price_krw is None, est_price_krw 는 **추정치**
            "price_basis": basis,
            "ask_price_krw": cand.ask_price_krw,     # 호가 없으면 None (위장 금지)
            "est_price_krw": price,                  # 판단·예산 비교에 실제로 쓴 값
            "price_estimated": basis != PRICE_BASIS_LISTING,
            # 호가 기준이면 시점 이야기가 필요 없다(지금 살 수 있는 값이다).
            # 실거래 기준이면 **언제 시점의 값인지**까지 말한다(CR34-5).
            "price_note": (None if basis == PRICE_BASIS_LISTING
                           else trade_basis_note(band)),
            "ask_gap_pct": (ask_gap_pct(cand.ask_price_krw, band)
                            if cand.ask_price_krw is not None and band.available else None),
            "price_band": _price_band_dict(band),
            # --- 점수 계약 (api-spec §5.3) ------------------------------------
            # total_score  : null 이면 "모름"(0 이 아니다)
            # score_basis  : user_weighted(사용자 가중치) | agent_scores(폴백) | null
            # score_axes   : 축별 가중치·점수·상태·빠진 사유 — **검증 가능한 형태로**
            # score_notes  : 반영되지 않은 가중치 고지(사람이 읽는 문장)
            # score_coverage_pct : 사용자 가중치 중 실제로 반영된 비율(%)
            "total_score": score.total,
            "score_basis": score.basis,
            "score_axes": [dict(row) for row in score.axes],
            "score_notes": list(score.notes),
            "score_coverage_pct": score.coverage_pct,
            # MVP 에는 타이밍 분석가가 없다. 없는 기능을 있는 척하지 않는다.
            "timing_signal": "unknown",
            "findings": [f.to_dict() for f in findings],
            # 요약(headline/why/why_not/next_actions)은 **순위를 매긴 뒤** 상위 후보에만
            # 만든다(아래 2패스). Finding 객체는 그때까지 여기 들고 간다 —
            # `_SUMMARY_INPUT_KEY` 는 응답에 나가기 전에 반드시 제거된다.
            _SUMMARY_INPUT_KEY: findings,
        })

    # 점수가 있는 후보가 먼저. 점수 없는 후보끼리는 **근거 표본이 많은 순**으로 둔다
    # (임의 순서로 잘라내면 top_n 이 사실상 DB 정렬 순서가 된다 — 그건 근거가 아니다).
    items.sort(key=lambda x: (
        x["total_score"] is not None,
        x["total_score"] if x["total_score"] is not None else 0.0,
        (x["price_band"] or {}).get("sample_size", 0),
    ), reverse=True)
    for rank, item in enumerate(items[:top_n], start=1):
        item["rank"] = rank

    # --- 2패스: 요약은 **살아남은 후보에만** 만든다 -------------------------
    #
    # 예전에는 후보를 도는 루프 안에서 요약을 만들었다. 그러면 상위 10건을 보여주려고
    # 후보 200건의 요약을 만들고 190건을 버린다 — LLM 이 붙는 순간 그 190건이 그대로
    # **돈과 지연**이 된다(그리고 아무도 읽지 않는다). 순위를 먼저 확정하고 여기서 만든다.
    budget = LLMBudget() if llm is not None else None
    for item in items[:top_n]:
        summary = portfolio_summary(item.pop(_SUMMARY_INPUT_KEY), llm, forbidden,
                                    budget=budget)
        item["headline"] = summary["headline"]
        item["why"] = summary["why"]
        item["why_not"] = summary["why_not"]
        item["next_actions"] = _merge_actions(summary["next_actions"],
                                              item["redevelopment"]["must_verify"])
        # 이 카드의 문장이 AI 가 쓴 것인지 규칙이 쓴 것인지 **카드 단위로** 밝힌다.
        # notes 만으로는 "어느 카드가 규칙 기반인지"를 사용자가 알 수 없다.
        item["summary_basis"] = summary["generated_by"]

    # 순위 밖 후보에는 요약을 만들지 않는다(어차피 응답에 나가지 않는다).
    # 다만 임시 키는 반드시 지운다 — Finding 객체가 남으면 직렬화가 깨진다.
    for item in items[top_n:]:
        item.pop(_SUMMARY_INPUT_KEY, None)

    # 순위에서 잘린 후보도 **사용자 입장에서는 "안 나온 후보"** 다. 조건을 다 통과하고도
    # 11위라서 빠진 단지를 아무 데도 안 남기면, 사용자는 그게 예산 때문인지 데이터가
    # 없어서인지 알 수 없다. 그래서 잘린 것도 사유와 함께 남긴다 —
    # 이로써 **모든 후보는 items 아니면 excluded 에 한 번씩 들어간다**(둘 다는 아니다).
    for item in items[top_n:]:
        excluded.append(_rank_cutoff_entry(item, top_n))

    notes = ["타이밍 분석(market-timing-analyst)은 2차 기능입니다.",
             "입지 분석은 데이터 수집 후 제공됩니다."]
    notes += time_adjust_notes(items[:top_n], attempted=ctx.market_indexes is not None)
    # "AI 추천"을 눌렀는데 요약이 규칙 기반이면 **그 사실을 말한다.**
    # 추천이 있는 경우에만 붙인다 — 후보가 0건이면 요약 자체가 없었으므로 할 말이 아니다.
    if items[:top_n]:
        notes += llm_notes(budget, llm_connected=llm is not None)
    # 가중치가 **어떻게 반영됐는지**(그리고 무엇이 반영되지 않았는지)를 목록 상단에도 말한다.
    # 개별 카드의 score_notes 만 남기면 사용자는 카드를 하나씩 열어야 알 수 있다.
    notes += summary_notes(weights=weights, unknown_keys=unknown_weight_keys,
                           results=scores, total_items=len(items), defaulted=defaulted)
    # 재건축 정보가 **확인되지 않은** 후보가 있으면 그 사실을 말한다.
    # 말하지 않으면 사용자는 "재건축 이슈가 없는 단지"로 읽는다 — 정반대일 수 있다.
    unknown_redev = sum(1 for it in items[:top_n]
                        if not (it.get("redevelopment") or {}).get("available"))
    if unknown_redev:
        notes.append(
            f"추천 {len(items[:top_n])}건 중 {unknown_redev}건은 정비사업 구역 정보가 "
            "확인되지 않았습니다 — '재건축 이슈가 없다'는 뜻이 아닙니다"
            "(수집 범위: 서울·인천. 경기도는 미수집).")
    if any((it.get("redevelopment") or {}).get("available") for it in items[:top_n]):
        notes.append(
            "재건축 판정은 고시된 진행 단계만 봅니다. **추가분담금은 조합 내부 자료라 "
            "공개 데이터에 없어 반영하지 않았습니다** — 금액은 조합에 직접 확인하세요.")
    if budget_unknown_area:
        # 후보 전체 기준이다. **통과시킨 사실을 말하는 고지**라서 상위 N 으로 줄이면
        # "몇 건을 판정 없이 통과시켰는가"가 사라진다(그게 이 문장의 존재 이유다).
        notes.append(
            f"후보 {budget_unknown_area}건은 전용면적이 확인되지 않아 예산 상한을 세우지 "
            "못했고, 예산 판정 없이 목록에 남겨 두었습니다 — 자산 기준 상한은 면적에 따라 "
            "달라지기 때문입니다(취득세 85㎡ 경계). '예산 안'이라는 뜻이 아닙니다.")
    if cost_guard_degraded:
        # 후보 전체(items+excluded) 기준이다. 상위 N 만 세면 "3건 보류"라고 해 놓고
        # 화면의 10건 어디에도 그 표시가 없는 상태가 생긴다.
        notes.append(
            f"후보 {cost_guard_degraded}건은 정비사업 판정 문장이 내부 금액 검사에 걸려 "
            "재건축 분석만 내려놓았습니다(해당 후보의 순위·가격 근거는 그대로입니다). "
            "'정비사업이 없다'는 뜻이 아닙니다.")
    if any(it["price_basis"] == PRICE_BASIS_TRADE for it in items[:top_n]):
        notes.append(
            "일부 후보는 현재 등록된 매물이 없어 최근 실거래 기준으로 세운 추정입니다"
            "(price_basis=trade). 호가와 달라 즉시 매수 가능한 가격이 아닙니다.")
    if any(it["total_score"] is None for it in items[:top_n]):
        notes.append(
            "점수를 매길 근거(호가 갭·입지 실측)가 없어 total_score 가 비어 있는 후보가 "
            "있습니다. 이 후보들은 실거래 표본이 많은 순으로 나열됩니다.")

    return {
        "items": items[:top_n],
        "excluded": excluded,
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }
