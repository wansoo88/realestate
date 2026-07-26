"""실거래 적재 — 정규화된 레코드를 complex / unit_type / trade 로 넣는다.

설계 근거: erd.md(3계층·파티션·ingest_log) · team/roles/re-data.md(중복제거·출처기록) ·
          docs/02-design/security.md §5(수집)

두 가지 구현
------------
- `InMemoryTradeLoader`: DB 없이 **적재 로직**(get-or-create·중복 dedup)을 검증한다.
  픽스처(실응답 XML) → parse → normalize → load 전 구간을 테스트로 못박는다.
- `PostgisTradeLoader`: 실제 PostGIS 적재(SQL). 키·DB 가 오면 이걸로 돈다.

둘은 **normalize.py 의 같은 키**를 쓴다 — 규칙이 갈리면 "테스트는 되는데 운영엔 중복"이 된다.

멱등성 · 해제 반영 (증분 재수집 · INGEST-2)
-------------------------------------------
증분 수집이 최근 2개월을 다시 받으므로 같은 거래가 반복 유입된다. trade 는 원천에
거래 ID 가 없어, 자연키(normalize.TradeNaturalKey = 단지·거래일·금액·면적·층, **is_cancelled
제외**)로 **찾아서 upsert** 한다. 정상 거래가 나중에 해제되어 재유입되면 기존 행의
is_cancelled 가 True 로 갱신되고, 시세 통계(NOT is_cancelled)에서 사라진다 — 허위신고 후
해제로 시세를 띄우는 조작을 걷어내는 것이 is_cancelled 추적의 목적이다(CHARTER §0).
PostGIS 는 유니크 제약이 아직 없어 `UPDATE→(없으면)INSERT` 로 멱등을 만든다(동시성·성능을
위해선 자연키 유니크 인덱스 권장 — re-arch 004 에 새 자연키로 반영 요청).
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.ingest import normalize
from app.ingest.molit import SOURCE_NAME, MolitTrade

#: (시군구5, 법정동명) → 법정동코드 10자리. 없으면 region_code 를 NULL 로 둔다.
#: region 마스터가 적재돼야 실제 매핑이 가능하다(별도 소스 — 행정표준 법정동코드).
RegionResolver = Callable[[str, str | None], str | None]


def build_region_mapping(rows: "Sequence[Any]") -> dict[tuple[str, str], str]:
    """region 행들 → (시군구5, MOLIT 법정동명) → 10자리 코드.

    ⚠️ INGEST-3 — 읍·면 지역은 MOLIT 이 '읍면 + 리' 를 붙여 준다
    ----------------------------------------------------------
    MOLIT `umdNm` 은 동 지역에서는 '오남동' 처럼 한 토막이지만, 읍·면 지역에서는
    **'오남읍 오남리'** 처럼 두 토막으로 온다. 읍면동 레벨(리 두 자리 '00')만 키로
    쓰면 이 이름이 어디에도 걸리지 않아 `region_code` 가 통째로 NULL 이 된다 —
    실측(2026-07-26): 신규 적재 9,009단지 중 1,009단지(11%)가 남양주·양평·가평·
    파주·김포·화성·용인 처인 등 읍면 지역에서 NULL 이었고, 그 결과
    (1) 시군구별 조회에서 사라지고 (2) 부동산원 매칭(법정동코드 기준)이 불가능해
    주소 경로 지오코딩까지 막혔다. 조용한 유실이라 더 나쁘다.

    그래서 리(里) 레벨도 키로 받되, **리 이름만으로는 절대 받지 않는다** —
    같은 시군구 안에 '진접읍 금곡리'와 '금곡동'이 함께 있어 겹친다. 부모 읍·면
    이름을 붙인 전체 이름('오남읍 오남리')만 키로 쓴다. 수도권 실측 1,537개 리 키가
    전부 유일했지만, 유일하지 않으면 **추측하지 않고 키를 버린다**.
    """
    eupmyeon: dict[tuple[str, str], str] = {}
    ri: dict[tuple[str, str], str | None] = {}      # None = 중복이라 못 쓰는 키
    for r in rows:
        code = (getattr(r, "code", "") or "").strip()
        dong = (getattr(r, "dong", "") or "").strip()
        if len(code) != 10 or not dong or code[5:8] == "000":
            continue
        if code[8:10] == "00":                       # 읍면동 레벨
            eupmyeon.setdefault((code[:5], dong), code)
            continue
        # 리 레벨 — 부모 읍·면 이름은 region.sigungu 의 마지막 토막이다
        # ('남양주시 오남읍' · '용인시 처인구 포곡읍').
        parent = (getattr(r, "sigungu", "") or "").strip().rsplit(" ", 1)[-1]
        if not parent.endswith(("읍", "면")) or " " in dong:
            continue                                 # 모양이 예상과 다르면 쓰지 않는다
        key = (code[:5], f"{parent} {dong}")
        if key in ri and ri[key] != code:
            ri[key] = None                           # 애매하면 버린다(엉뚱한 동에 붙지 않게)
        else:
            ri.setdefault(key, code)

    mapping = dict(eupmyeon)
    for key, code in ri.items():
        if code is not None:
            mapping.setdefault(key, code)            # 읍면동 키가 이기게 둔다
    return mapping


def make_db_region_resolver(engine: Any) -> RegionResolver:
    """`region` 테이블을 한 번 읽어 (시군구5, 법정동명) → 10자리 코드로 매핑한다.

    왜 미리 통째로 읽는가
    ---------------------
    적재 루프 안에서 단지마다 SELECT 하면 수만 번의 왕복이 된다. 수도권 법정동은
    3천 건(리 포함 4.5천) 규모라 메모리에 올려도 무시할 크기다(소형 VPS 라 중요하다).

    ⚠️ 매핑되지 않으면 **추측하지 않고 None** 을 준다 — 틀린 지역코드는 틀린 지역
       통계를 낳고, complex.region_code 는 FK 라 없는 코드를 넣으면 적재가 통째로 깨진다.
       키 구성 규칙은 `build_region_mapping` 참조(읍면동 + '읍면 리' 전체 이름).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT code, sigungu, dong FROM region
            WHERE dong IS NOT NULL
              AND substr(code, 6, 3) <> '000'
            ORDER BY code
        """)).all()
    mapping = build_region_mapping(rows)

    def resolve(sgg5: str, legal_dong: str | None) -> str | None:
        if not legal_dong:
            return None
        return mapping.get((sgg5, legal_dong.strip()))

    return resolve


@dataclass
class LoadResult:
    """한 번 이상의 load() 누적 결과. ingest_log 보완 지표.

    trades_updated: 자연키가 이미 있어 upsert 된 건수. 재수집 멱등의 결과이자,
    **정상→해제 갱신**(INGEST-2)도 여기 잡힌다.
    """

    complexes_created: int = 0
    unit_types_created: int = 0
    trades_inserted: int = 0
    trades_updated: int = 0

    def _add(self, other: "LoadResult") -> None:
        self.complexes_created += other.complexes_created
        self.unit_types_created += other.unit_types_created
        self.trades_inserted += other.trades_inserted
        self.trades_updated += other.trades_updated


class TradeLoader(Protocol):
    """runner 의 row_sink 로 꽂히는 적재기. 배치를 받아 적재하고 결과를 누적한다."""

    totals: LoadResult

    def load(self, trades: Sequence[MolitTrade]) -> LoadResult: ...


# ---------------------------------------------------------------------------
# 인메모리 — 적재 로직 검증용 (DB 불필요)
# ---------------------------------------------------------------------------

@dataclass
class _StoredComplex:
    id: int
    key: normalize.ComplexKey
    region_code: str | None
    geom: tuple[float, float] | None = None   # (lon, lat) — 지오코딩 후 채움


class InMemoryTradeLoader:
    """dict 기반 적재. get-or-create·자연키 upsert 를 PostGIS 구현과 동일 규칙으로 흉내낸다."""

    def __init__(self, *, region_resolver: RegionResolver | None = None) -> None:
        self._resolver = region_resolver
        self.complexes: dict[normalize.ComplexKey, _StoredComplex] = {}
        self.unit_types: dict[normalize.UnitTypeKey, int] = {}
        self.trades: dict[normalize.TradeNaturalKey, dict[str, Any]] = {}
        self.totals = LoadResult()
        self._seq_complex = 0
        self._seq_unit = 0

    def _get_or_create_complex(self, t: MolitTrade, res: LoadResult) -> _StoredComplex:
        key = normalize.complex_key(t)
        found = self.complexes.get(key)
        if found is not None:
            return found
        self._seq_complex += 1
        region_code = self._resolver(key.region_sgg5, key.legal_dong) if self._resolver else None
        stored = _StoredComplex(id=self._seq_complex, key=key, region_code=region_code)
        self.complexes[key] = stored
        res.complexes_created += 1
        return stored

    def _get_or_create_unit_type(self, t: MolitTrade, res: LoadResult) -> int:
        key = normalize.unit_type_key(t)
        found = self.unit_types.get(key)
        if found is not None:
            return found
        self._seq_unit += 1
        self.unit_types[key] = self._seq_unit
        res.unit_types_created += 1
        return self._seq_unit

    def load(self, trades: Sequence[MolitTrade]) -> LoadResult:
        res = LoadResult()
        for t in trades:
            cx = self._get_or_create_complex(t, res)
            ut = self._get_or_create_unit_type(t, res)
            nk = normalize.trade_natural_key(t)
            row = {
                "complex_id": cx.id, "unit_type_id": ut,
                "contract_date": t.contract_date, "price_krw": t.price_krw,
                "floor": t.floor, "area_m2": normalize._norm_area(t.area_m2),
                "apt_dong": t.apt_dong,   # 저장만 — 자연키 아님(결측 있어 키 흔들림 방지)
                "is_cancelled": t.is_cancelled, "cancelled_on": t.cancelled_on,
                "source": t.source,
            }
            # upsert: 자연키(is_cancelled 제외)가 이미 있으면 최신값으로 덮어쓴다.
            # 정상 거래가 해제되어 재유입되면 기존 행의 is_cancelled 가 True 로 갱신되고,
            # NOT is_cancelled 로 거르는 시세 통계에서 사라진다(INGEST-2).
            if nk in self.trades:
                # apt_dong 은 PostGIS 로더의 COALESCE(:apt_dong, apt_dong) 와 동일하게 다룬다:
                # 결측(None) 으로 재유입돼도 기존 동을 지우지 않는다(APTDONG-1, 두 로더 동일 규칙).
                if row["apt_dong"] is None:
                    row["apt_dong"] = self.trades[nk].get("apt_dong")
                self.trades[nk] = row
                res.trades_updated += 1
            else:
                self.trades[nk] = row
                res.trades_inserted += 1
        self.totals._add(res)
        return res

    def active_trades(self) -> list[dict[str, Any]]:
        """시세로 쓰는 거래 = 해제되지 않은 거래(NOT is_cancelled). 테스트·검증용 뷰."""
        return [row for row in self.trades.values() if not row["is_cancelled"]]


# ---------------------------------------------------------------------------
# PostGIS — 실제 적재 (키·DB 준비되면 사용)
# ---------------------------------------------------------------------------

class PostgisTradeLoader:
    """PostGIS 적재기. base.py 리포지토리와 별개로 ingest 가 소유하는 쓰기 어댑터.

    complex·unit_type 는 get-or-create, trade 는 자연키 dedup(WHERE NOT EXISTS)로 멱등.
    ⚠️ region_code 를 NULL 이 아닌 값으로 넣으려면 region 마스터가 적재돼 있어야 한다
       (FK). resolver 미주입 시 NULL 로 두므로 안전하다.
    """

    def __init__(self, engine: Any, *, region_resolver: RegionResolver | None = None,
                 source: str = SOURCE_NAME) -> None:
        self._engine = engine
        self._resolver = region_resolver
        self._source = source
        self.totals = LoadResult()

    def load(self, trades: Sequence[MolitTrade]) -> LoadResult:
        from sqlalchemy import text
        res = LoadResult()
        # 배치 안에서 같은 단지/타입 재조회를 줄이는 캐시.
        cx_cache: dict[normalize.ComplexKey, int] = {}
        ut_cache: dict[normalize.UnitTypeKey, int] = {}

        with self._engine.begin() as conn:
            for t in trades:
                cid = self._complex_id(conn, text, t, cx_cache, res)
                uid = self._unit_type_id(conn, text, t, cid, ut_cache, res)
                self._upsert_trade(conn, text, t, cid, uid, res)
        self.totals._add(res)
        return res

    def _complex_id(self, conn, text, t: MolitTrade,
                    cache: dict, res: LoadResult) -> int:
        key = normalize.complex_key(t)
        if key in cache:
            return cache[key]
        region_code = self._resolver(key.region_sgg5, key.legal_dong) if self._resolver else None
        params = {"name": key.name, "dong": key.legal_dong, "rc": region_code}
        row = conn.execute(text("""
            SELECT id FROM complex
            WHERE name = :name
              AND address_jibun IS NOT DISTINCT FROM :dong
              AND region_code IS NOT DISTINCT FROM :rc
            ORDER BY id LIMIT 1
        """), params).one_or_none()
        if row is None:
            row = conn.execute(text("""
                INSERT INTO complex (region_code, name, address_jibun, source, updated_at)
                VALUES (:rc, :name, :dong, :source, now())
                RETURNING id
            """), {**params, "source": self._source}).one()
            res.complexes_created += 1
        cache[key] = row.id
        return row.id

    def _unit_type_id(self, conn, text, t: MolitTrade, complex_id: int,
                      cache: dict, res: LoadResult) -> int:
        key = normalize.unit_type_key(t)
        if key in cache:
            return cache[key]
        params = {"cid": complex_id, "area": key.area_m2}
        row = conn.execute(text("""
            SELECT id FROM unit_type
            WHERE complex_id = :cid AND area_m2 = :area AND type_name IS NULL
            ORDER BY id LIMIT 1
        """), params).one_or_none()
        if row is None:
            row = conn.execute(text("""
                INSERT INTO unit_type (complex_id, area_m2) VALUES (:cid, :area)
                RETURNING id
            """), params).one()
            res.unit_types_created += 1
        cache[key] = row.id
        return row.id

    def _upsert_trade(self, conn, text, t: MolitTrade, complex_id: int,
                      unit_type_id: int, res: LoadResult) -> None:
        params = {
            "cid": complex_id, "uid": unit_type_id,
            "contract_date": t.contract_date, "price": t.price_krw,
            "floor": t.floor, "area": normalize._norm_area(t.area_m2),
            "apt_dong": t.apt_dong,   # 저장만 — 자연키 아님(결측 있어 키 흔들림 방지, INGEST-2 논리)
            "cancelled": t.is_cancelled, "cancelled_on": t.cancelled_on,
            "registered": t.registered_at, "trade_type": t.trade_type,
            "source": t.source, "ingested_at": t.ingested_at,
        }
        # upsert by **자연키(is_cancelled 제외)** — INGEST-2.
        # 먼저 UPDATE. 매치되면 해제여부까지 최신값으로 갱신된다(정상→해제 시 원본 행이
        # is_cancelled=True 로 바뀌어 시세 통계 NOT is_cancelled 에서 사라진다).
        # 유니크 제약이 아직 없어 ON CONFLICT 대신 UPDATE→(없으면)INSERT 로 멱등을 만든다.
        updated = conn.execute(text("""
            UPDATE trade SET
                unit_type_id = :uid,
                apt_dong = COALESCE(:apt_dong, apt_dong),
                is_cancelled = :cancelled,
                registered_at = :registered,
                trade_type = :trade_type,
                source = :source,
                ingested_at = :ingested_at
            WHERE complex_id = :cid
              AND contract_date = :contract_date
              AND price_krw = :price
              AND area_m2 IS NOT DISTINCT FROM :area
              AND floor IS NOT DISTINCT FROM :floor
        """), params)
        if updated.rowcount and updated.rowcount > 0:
            res.trades_updated += 1
            return
        conn.execute(text("""
            INSERT INTO trade (complex_id, unit_type_id, contract_date, price_krw,
                               floor, area_m2, apt_dong, is_cancelled, registered_at,
                               trade_type, source, ingested_at)
            VALUES (:cid, :uid, :contract_date, :price, :floor, :area, :apt_dong,
                    :cancelled, :registered, :trade_type, :source, :ingested_at)
        """), params)
        res.trades_inserted += 1
