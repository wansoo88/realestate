"""실거래 적재 — 정규화된 레코드를 complex / unit_type / trade 로 넣는다.

설계 근거: erd.md(3계층·파티션·ingest_log) · team/roles/re-data.md(중복제거·출처기록) ·
          docs/02-design/security.md §5(수집)

두 가지 구현
------------
- `InMemoryTradeLoader`: DB 없이 **적재 로직**(get-or-create·중복 dedup)을 검증한다.
  픽스처(실응답 XML) → parse → normalize → load 전 구간을 테스트로 못박는다.
- `PostgisTradeLoader`: 실제 PostGIS 적재(SQL). 키·DB 가 오면 이걸로 돈다.

둘은 **normalize.py 의 같은 키**를 쓴다 — 규칙이 갈리면 "테스트는 되는데 운영엔 중복"이 된다.

멱등성 (증분 재수집)
--------------------
증분 수집이 최근 2개월을 다시 받으므로 같은 거래가 반복 유입된다. trade 는 원천에
거래 ID 가 없어, 자연키(normalize.TradeDedupKey)로 **이미 있으면 건너뛴다**. PostGIS 는
`WHERE NOT EXISTS` 로 처리 — 유니크 제약 없이도 멱등하다(동시성·성능을 위해선 자연키
유니크 인덱스를 권장, re-arch 에 별도 요청).
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
    """한 번 이상의 load() 누적 결과. ingest_log 보완 지표."""

    complexes_created: int = 0
    unit_types_created: int = 0
    trades_inserted: int = 0
    trades_skipped_dup: int = 0

    def _add(self, other: "LoadResult") -> None:
        self.complexes_created += other.complexes_created
        self.unit_types_created += other.unit_types_created
        self.trades_inserted += other.trades_inserted
        self.trades_skipped_dup += other.trades_skipped_dup


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
    """dict 기반 적재. get-or-create·중복 dedup 을 PostGIS 구현과 동일 규칙으로 흉내낸다."""

    def __init__(self, *, region_resolver: RegionResolver | None = None) -> None:
        self._resolver = region_resolver
        self.complexes: dict[normalize.ComplexKey, _StoredComplex] = {}
        self.unit_types: dict[normalize.UnitTypeKey, int] = {}
        self.trades: dict[normalize.TradeDedupKey, dict[str, Any]] = {}
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
            dk = normalize.trade_dedup_key(t)
            if dk in self.trades:
                res.trades_skipped_dup += 1
                continue
            self.trades[dk] = {
                "complex_id": cx.id, "unit_type_id": ut,
                "contract_date": t.contract_date, "price_krw": t.price_krw,
                "floor": t.floor, "area_m2": normalize._norm_area(t.area_m2),
                "is_cancelled": t.is_cancelled, "source": t.source,
            }
            res.trades_inserted += 1
        self.totals._add(res)
        return res


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
                self._insert_trade(conn, text, t, cid, uid, res)
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

    def _insert_trade(self, conn, text, t: MolitTrade, complex_id: int,
                      unit_type_id: int, res: LoadResult) -> None:
        params = {
            "cid": complex_id, "uid": unit_type_id,
            "contract_date": t.contract_date, "price": t.price_krw,
            "floor": t.floor, "area": normalize._norm_area(t.area_m2),
            "cancelled": t.is_cancelled, "registered": t.registered_at,
            "trade_type": t.trade_type, "source": t.source,
            "ingested_at": t.ingested_at,
        }
        # 자연키 dedup — 이미 있으면 넣지 않는다(증분 재수집 멱등).
        result = conn.execute(text("""
            INSERT INTO trade (complex_id, unit_type_id, contract_date, price_krw,
                               floor, area_m2, is_cancelled, registered_at,
                               trade_type, source, ingested_at)
            SELECT :cid, :uid, :contract_date, :price, :floor, :area, :cancelled,
                   :registered, :trade_type, :source, :ingested_at
            WHERE NOT EXISTS (
                SELECT 1 FROM trade tr
                WHERE tr.complex_id = :cid
                  AND tr.contract_date = :contract_date
                  AND tr.price_krw = :price
                  AND tr.area_m2 IS NOT DISTINCT FROM :area
                  AND tr.floor IS NOT DISTINCT FROM :floor
                  AND tr.is_cancelled = :cancelled
            )
        """), params)
        if result.rowcount and result.rowcount > 0:
            res.trades_inserted += 1
        else:
            res.trades_skipped_dup += 1
