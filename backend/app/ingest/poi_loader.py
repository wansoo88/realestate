"""입지 데이터 적재 — poi · road_segment · transit_plan.

설계 근거: migrations/011(자연키) · erd.md · team/roles/re-data.md(멱등·출처기록)

멱등성
------
`(source, source_ref)` 유니크(011) 위에서 `ON CONFLICT ... DO UPDATE` 한다.
재실행해도 행이 쌓이지 않고 좌표·이름·attrs 만 갱신된다. 자연키를 원천 ID 로 둔
근거는 011 주석 참조(이름·좌표를 키로 쓰면 원천이 1m 고칠 때마다 행이 늘어난다).

⚠️ **배치 안에서도 먼저 접는다**(poi.dedupe). 같은 INSERT 명령이 같은 대상 행을 두 번
   건드리면 PostgreSQL 이 `ON CONFLICT DO UPDATE command cannot affect row a second
   time` 로 트랜잭션 전체를 깬다 — 타일을 나눠 받으면 경계에서 반드시 발생한다.

메모리
------
운영 VPS 는 가용 메모리가 200MB 안팎이다. 전건을 한 번에 넘기지 않고 `chunk_size`
단위로 끊어 보낸다. 도로 2.4만 건을 한 트랜잭션에 넣으면 서버가 아니라 **다른 실서비스**가
먼저 죽는다.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.ingest.poi import PoiRecord, RoadRecord, TransitPlanRecord

logger = logging.getLogger("ingest.poi_loader")

#: 한 번에 보낼 행 수. 소형 VPS 라 크게 잡지 않는다.
DEFAULT_CHUNK = 500


@dataclass
class PoiLoadResult:
    """적재 결과. ingest_log 의 rows_ok/rows_failed 근거."""

    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.inserted + self.updated

    def merge(self, other: "PoiLoadResult") -> "PoiLoadResult":
        return PoiLoadResult(
            inserted=self.inserted + other.inserted,
            updated=self.updated + other.updated,
            skipped=self.skipped + other.skipped,
        )


_POI_UPSERT = """
    INSERT INTO poi (category, name, geom, attrs, source, source_ref)
    VALUES (:category, :name,
            ST_SetSRID(ST_MakePoint(CAST(:lon AS double precision),
                                    CAST(:lat AS double precision)), 4326),
            CAST(:attrs AS jsonb), :source, :source_ref)
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET name  = EXCLUDED.name,
                  geom  = EXCLUDED.geom,
                  attrs = EXCLUDED.attrs,
                  category = EXCLUDED.category
    RETURNING (xmax = 0) AS inserted
"""

_ROAD_UPSERT = """
    INSERT INTO road_segment (name, road_class, lanes, geom, source, source_url,
                              as_of, source_ref)
    VALUES (:name, :road_class, :lanes,
            ST_SetSRID(ST_GeomFromText(:wkt), 4326),
            :source, :source_url, CAST(:as_of AS date), :source_ref)
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET name       = EXCLUDED.name,
                  road_class = EXCLUDED.road_class,
                  lanes      = EXCLUDED.lanes,
                  geom       = EXCLUDED.geom,
                  as_of      = EXCLUDED.as_of
    RETURNING (xmax = 0) AS inserted
"""

_PLAN_UPSERT = """
    INSERT INTO transit_plan (name, geom, open_expected, status, source_url,
                              source, source_ref)
    VALUES (:name, ST_SetSRID(ST_GeomFromText(:wkt), 4326),
            CAST(:open_expected AS date), :status, :source_url,
            :source, :source_ref)
    ON CONFLICT (source, source_ref) WHERE source_ref IS NOT NULL
    DO UPDATE SET name          = EXCLUDED.name,
                  geom          = EXCLUDED.geom,
                  open_expected = EXCLUDED.open_expected,
                  status        = EXCLUDED.status,
                  source_url    = EXCLUDED.source_url
    RETURNING (xmax = 0) AS inserted
"""


def _chunks(items: Sequence[Any], size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class PostgisPoiLoader:
    """PostGIS 적재기. 표별 upsert 를 같은 규칙으로 처리한다."""

    def __init__(self, engine: Any, *, chunk_size: int = DEFAULT_CHUNK) -> None:
        self._engine = engine
        self._chunk = max(1, chunk_size)

    # -- 공통 ------------------------------------------------------------

    def _run(self, sql: str, params: list[dict[str, Any]]) -> PoiLoadResult:
        """청크 단위 upsert. `xmax = 0` 으로 신규/갱신을 가른다.

        `xmax` 는 그 행을 지운 트랜잭션 ID다. INSERT 로 새로 생긴 행은 0 이고,
        ON CONFLICT 로 UPDATE 된 행은 0 이 아니다 — 별도 SELECT 없이 구분된다.
        """
        from sqlalchemy import text

        stmt = text(sql)
        result = PoiLoadResult()
        for chunk in _chunks(params, self._chunk):
            with self._engine.begin() as conn:
                for row in chunk:
                    inserted = conn.execute(stmt, row).scalar_one()
                    if inserted:
                        result.inserted += 1
                    else:
                        result.updated += 1
        return result

    # -- poi -------------------------------------------------------------

    def load_pois(self, records: Sequence[PoiRecord]) -> PoiLoadResult:
        params: list[dict[str, Any]] = []
        skipped = 0
        for rec in records:
            if not rec.source_ref or rec.lon is None or rec.lat is None:
                # 자연키나 좌표가 없으면 멱등을 보장할 수 없고 공간쿼리도 못 탄다.
                skipped += 1
                continue
            params.append({
                "category": rec.category,
                "name": rec.name,
                "lon": float(rec.lon),
                "lat": float(rec.lat),
                # None 값은 attrs 에 남기지 않는다 — `attrs->>'x'` 가 NULL 과
                # 'null' 문자열로 갈리는 혼란을 만들지 않기 위해서다.
                "attrs": json.dumps(
                    {k: v for k, v in (rec.attrs or {}).items() if v is not None},
                    ensure_ascii=False),
                "source": rec.source,
                "source_ref": rec.source_ref,
            })
        out = self._run(_POI_UPSERT, params)
        out.skipped += skipped
        return out

    # -- road_segment ----------------------------------------------------

    def load_roads(self, records: Sequence[RoadRecord]) -> PoiLoadResult:
        params: list[dict[str, Any]] = []
        skipped = 0
        for rec in records:
            if not rec.source_ref or not rec.wkt:
                skipped += 1
                continue
            params.append({
                "name": rec.name,
                "road_class": rec.road_class,
                "lanes": rec.lanes,
                "wkt": rec.wkt,
                "source": rec.source,
                "source_url": rec.source_url,
                "as_of": rec.as_of,
                "source_ref": rec.source_ref,
            })
        out = self._run(_ROAD_UPSERT, params)
        out.skipped += skipped
        return out

    # -- transit_plan ----------------------------------------------------

    def load_transit_plans(
        self, records: Sequence[TransitPlanRecord], *, source: str,
    ) -> PoiLoadResult:
        params: list[dict[str, Any]] = []
        skipped = 0
        for rec in records:
            if not rec.source_ref or not rec.wkt or not rec.name:
                skipped += 1
                continue
            params.append({
                "name": rec.name,
                "wkt": rec.wkt,
                "open_expected": rec.open_expected,
                "status": rec.status,
                "source_url": rec.source_url,
                "source": source,
                "source_ref": rec.source_ref,
            })
        out = self._run(_PLAN_UPSERT, params)
        out.skipped += skipped
        return out


class InMemoryPoiLoader:
    """DB 없이 적재 규칙(멱등·건너뜀)을 검증하기 위한 구현.

    운영 구현과 **같은 자연키**를 쓴다 — 규칙이 갈리면 "테스트는 되는데 운영엔 중복"이 된다.
    """

    def __init__(self) -> None:
        self.pois: dict[tuple[str, str], PoiRecord] = {}
        self.roads: dict[tuple[str, str], RoadRecord] = {}
        self.plans: dict[tuple[str, str], TransitPlanRecord] = {}

    @staticmethod
    def _apply(store: dict, key: tuple[str, str], value: Any) -> PoiLoadResult:
        if key in store:
            store[key] = value
            return PoiLoadResult(updated=1)
        store[key] = value
        return PoiLoadResult(inserted=1)

    def load_pois(self, records: Sequence[PoiRecord]) -> PoiLoadResult:
        out = PoiLoadResult()
        for rec in records:
            if not rec.source_ref or rec.lon is None or rec.lat is None:
                out.skipped += 1
                continue
            out = out.merge(self._apply(self.pois, (rec.source, rec.source_ref), rec))
        return out

    def load_roads(self, records: Sequence[RoadRecord]) -> PoiLoadResult:
        out = PoiLoadResult()
        for rec in records:
            if not rec.source_ref or not rec.wkt:
                out.skipped += 1
                continue
            out = out.merge(self._apply(self.roads, (rec.source, rec.source_ref), rec))
        return out

    def load_transit_plans(self, records: Sequence[TransitPlanRecord], *,
                           source: str) -> PoiLoadResult:
        out = PoiLoadResult()
        for rec in records:
            if not rec.source_ref or not rec.wkt or not rec.name:
                out.skipped += 1
                continue
            out = out.merge(self._apply(self.plans, (source, rec.source_ref), rec))
        return out
