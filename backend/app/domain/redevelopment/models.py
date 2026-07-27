"""정비사업 도메인 모델 — **수집된 사실만** 담는다.

여기 없는 것이 곧 "우리가 모르는 것"이다. 특히:
  * **추가분담금 필드가 없다.** 조합 내부 자료라 공개 데이터에 없으므로, 담을 자리를
    만들어 두면 언젠가 누가 추정치를 넣는다. 자리를 만들지 않는 것이 방어다.
  * **대지지분·용적률이 없다.** 정비사업 데이터에 없다(단지 쪽 `complex` 에 있고,
    그건 별도 사실이다). 두 출처를 한 객체에 섞으면 근거 추적이 끊긴다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

# 매칭 방법 — "이 정비구역이 왜 이 단지의 것인가"에 답하는 값.
#: 정비구역 대표지번의 (법정동코드·본번·부번)이 부동산원 단지 필지와 **완전히 같다.**
MATCH_PNU_EXACT = "pnu_exact"
#: 위와 같되, 주소의 행정동 표기('목2동')를 법정동('목동')으로 되돌려 맞췄다.
#: 지번 자체는 법정동 기준이므로 값은 같지만, 한 단계 덜 직접적이라 구분해 남긴다.
MATCH_PNU_ADMIN_DONG = "pnu_exact_admin_dong"

MATCH_METHODS = (MATCH_PNU_EXACT, MATCH_PNU_ADMIN_DONG)

# --- 출처 (SR25-3) ----------------------------------------------------------
#
# `source` 는 **DB 자연키**다(`redev_project(source, source_key)` · 적재 시 이 값으로
# 지우고 다시 넣는다). 그래서 값을 바꾸면 이미 적재된 616행이 고아가 되고 중복이 생긴다.
# 반면 사용자 화면·리포트의 출처 표기는 **사람이 읽는 이름**이어야 한다 —
# 공공누리 4유형의 '출처표시' 의무는 `seoul_opendata_TbSeoulRedevStatus` 같은
# 기계 키로 충족되지 않고, 그 키에는 SR24-1 로 **삭제한 OpenAPI 테이블명**이 남아 있어
# 실제 출처(무키 CSV, OA-22856)와도 어긋난다.
#
# 그래서 **식별자와 표시명을 분리**한다. 키는 그대로 두고(마이그레이션 불필요),
# 화면에 나가는 것은 아래 라벨이다.
SOURCE_SEOUL = "seoul_opendata_TbSeoulRedevStatus"
SOURCE_INCHEON = "datago_15055212_incheon"

#: 화면·리포트용 출처명. 공공누리 출처표시 요건은 이 문자열이 충족한다.
SOURCE_LABELS: dict[str, str] = {
    SOURCE_SEOUL: "서울특별시 열린데이터광장 — 정비사업 추진현황(OA-22856)",
    SOURCE_INCHEON: "인천광역시 — 공공데이터포털 정비사업 추진현황(15055212)",
}

#: 출처를 모를 때의 표기. 빈 문자열을 그대로 내보내지 않는다(출처 없는 주장 금지).
SOURCE_FALLBACK = "정비사업 추진현황"


def source_label(source: str | None) -> str:
    """기계 키 → 사람이 읽는 출처명. 모르는 키는 **그대로** 돌려준다.

    모르는 키를 fallback 으로 뭉개면, 새 출처를 추가하고 라벨을 잊었을 때
    화면에서 출처가 조용히 '정비사업 추진현황'으로 바뀐다 — 그건 틀린 출처표시다.
    """
    if not source:
        return SOURCE_FALLBACK
    return SOURCE_LABELS.get(source, source)


@dataclass(frozen=True)
class RedevProject:
    """단지 하나에 매칭된 정비사업 구역 1건.

    ⚠️ 날짜 필드는 **서울 자료에만** 있다(인천은 단계만 제공). 없으면 `None` 이고,
    `None` 은 "그 단계를 안 밟았다"가 아니라 **"모른다"** 이다. 두 뜻을 섞으면
    '정체 기간' 계산이 조용히 거짓이 된다(analysis 가 이 구분을 지킨다).
    """

    zone_name: str
    sigungu: str
    #: 원문 단계명. **항상 보존한다** — 화면에도 이 값을 함께 보여준다.
    raw_stage: str
    #: 공통 enum(stages.py). 표에 없으면 'unknown'.
    stage: str
    raw_biz_type: str | None = None
    biz_type: str = "unknown"
    source: str = ""
    source_url: str | None = None
    #: 이 스냅샷의 기준일(자료 갱신일). 언제 기준 사실인지 없으면 근거가 아니다.
    as_of: dt.date | None = None
    match_method: str = MATCH_PNU_EXACT

    # --- 단계별 일자 (서울 자료) --------------------------------------------
    zone_designated_on: dt.date | None = None
    committee_on: dt.date | None = None
    association_on: dt.date | None = None
    design_review_on: dt.date | None = None
    implementation_on: dt.date | None = None
    disposition_on: dt.date | None = None
    relocation_start_on: dt.date | None = None
    relocation_end_on: dt.date | None = None
    construction_start_on: dt.date | None = None

    # --- 규모 (서울 자료) ----------------------------------------------------
    #: 기존 가구수(멸실량).
    existing_households: int | None = None
    #: 건립 예정 세대수 총합. **분양가·분담금이 아니다** — 세대수일 뿐이다.
    planned_households: int | None = None

    @property
    def milestone_dates(self) -> tuple[dt.date, ...]:
        """확인된 단계 일자 전부(오름차순). 없으면 빈 튜플."""
        dates = [
            d for d in (
                self.zone_designated_on, self.committee_on, self.association_on,
                self.design_review_on, self.implementation_on, self.disposition_on,
                self.relocation_start_on, self.relocation_end_on,
                self.construction_start_on,
            ) if d is not None
        ]
        return tuple(sorted(dates))

    @property
    def last_milestone_on(self) -> dt.date | None:
        """가장 최근에 확인된 단계 일자. 모르면 None."""
        dates = self.milestone_dates
        return dates[-1] if dates else None

    @property
    def supply_ratio(self) -> float | None:
        """건립 예정 세대수 ÷ 기존 가구수. 둘 중 하나라도 모르면 None.

        **사업성의 방향**을 보는 값이다(일반분양 물량이 얼마나 나오는가).
        분담금 금액이 아니다 — 이 비율로 금액을 역산해 적는 것은 금지다.
        """
        if not self.existing_households or not self.planned_households:
            return None
        if self.existing_households <= 0:
            return None
        return round(self.planned_households / self.existing_households, 3)
