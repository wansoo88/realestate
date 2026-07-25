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
                "is_cancelled": t.is_cancelled, "cancelled_on": t.cancelled_on,
                "source": t.source,
            }
            # upsert: 자연키(is_cancelled 제외)가 이미 있으면 최신값으로 덮어쓴다.
            # 정상 거래가 해제되어 재유입되면 기존 행의 is_cancelled 가 True 로 갱신되고,
            # NOT is_cancelled 로 거르는 시세 통계에서 사라진다(INGEST-2).
            if nk in self.trades:
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
                               floor, area_m2, is_cancelled, registered_at,
                               trade_type, source, ingested_at)
            VALUES (:cid, :uid, :contract_date, :price, :floor, :area, :cancelled,
                    :registered, :trade_type, :source, :ingested_at)
        """), params)
        res.trades_inserted += 1
