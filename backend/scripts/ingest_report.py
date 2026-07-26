"""수집 결과 점검표 — 적재가 "됐다"가 아니라 **무엇이 얼마나 들어왔는지** 본다.

보는 것
-------
1. `ingest_log` 최근 실행 (성공/실패가 실제로 남았는가 — 조용한 실패 탐지)
2. `trade` 행수 · 기간 · 시군구 분포
3. **`apt_dong` 채움률** — F4(동별 실측)의 가용성. 설계 기대 77~93%
4. 해제거래(is_cancelled) 비율 — 시세 통계에서 빠져야 하는 물량
5. `complex` 좌표(geom) 보유율 · region_code(FK) 매핑률 · **좌표 출처/신뢰도**
6. **좌표 충돌** — 서로 다른 단지가 같은 점을 쓰면 최소 하나는 틀린 좌표다
7. **부동산원 매칭률**과 동(棟) 정보 — 매칭 못 한 단지는 주소·동수를 모르는 단지다
8. 중복 의심 — 같은 자연키가 2행 이상이면 멱등이 깨진 것

⚠️ 왜 좌표 충돌을 여기서 반드시 보나 (CR-020 GEO-1)
--------------------------------------------------
이 리포트는 한동안 `geom_pct 93.6%` 만 보고했고, 그 뒤에 **좌표가 완전히 같은 단지
514건(그중 68건은 법정동까지 다름)** 이 숨어 있었다. 확보율은 품질이 아니다.
"얼마나 채웠나"와 "얼마나 틀렸나"를 **같이** 보여주지 않으면 리포트가 결함을 덮는다.
`crossdong_rows` 는 **항상 0이어야 한다** — 0이 아니면 지오코딩이 다시 새고 있는 것이다.

⚠️ CR-021 GEO-3 — 법정동이 같아도 다른 단지일 수 있다
-----------------------------------------------------
`crossdong_rows` 가 0이 됐을 때 "남은 충돌은 전부 같은 단지의 이름 변형"이라고 결론냈는데,
부동산원 마스터가 그걸 반증했다 — 같은 점을 쓰면서 `reb_complex_id` 가 **서로 다른**
그룹이 15개(30단지) 있었다(역삼동 720-25 457세대 vs 824-25 168세대가 한 점).
그래서 `reb_conflict_rows` 도 **항상 0이어야 하는 지표**로 같이 본다. 법정동 대조는
"다른 동에 찍혔나"만 잡고, 번호 대조는 "같은 동 안에서 남의 단지에 붙었나"를 잡는다.

사용
----
    export DATABASE_URL=...
    python scripts/ingest_report.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import database_url, load_env, make_engine, safe_dsn  # noqa: E402

QUERIES: list[tuple[str, str]] = [
    ("ingest_log 최근 10건", """
        SELECT id, source, target_table, status, rows_ok, rows_failed,
               to_char(started_at, 'MM-DD HH24:MI') AS started, left(message, 90) AS message
        FROM ingest_log ORDER BY id DESC LIMIT 10
    """),
    ("trade 총계", """
        SELECT count(*) AS trades,
               count(*) FILTER (WHERE is_cancelled) AS cancelled,
               count(DISTINCT complex_id) AS complexes,
               min(contract_date) AS first_date, max(contract_date) AS last_date
        FROM trade
    """),
    ("apt_dong 채움률 (F4 동별 실측 가용성)", """
        SELECT count(*) AS trades,
               count(apt_dong) AS with_dong,
               round(100.0 * count(apt_dong) / NULLIF(count(*), 0), 1) AS pct
        FROM trade
    """),
    ("시군구별 (상위 15)", """
        SELECT coalesce(substr(r.code, 1, 5), '(미매핑)') AS sgg,
               coalesce(max(r.sigungu), '?') AS name,
               count(*) AS trades,
               round(100.0 * count(t.apt_dong) / NULLIF(count(*), 0), 1) AS dong_pct
        FROM trade t
        JOIN complex c ON c.id = t.complex_id
        LEFT JOIN region r ON r.code = c.region_code
        GROUP BY 1 ORDER BY trades DESC LIMIT 15
    """),
    ("월별 건수", """
        SELECT to_char(contract_date, 'YYYY-MM') AS ym, count(*) AS trades,
               count(*) FILTER (WHERE is_cancelled) AS cancelled
        FROM trade GROUP BY 1 ORDER BY 1
    """),
    ("complex 좌표·지역코드", """
        SELECT count(*) AS complexes,
               count(geom) AS with_geom,
               round(100.0 * count(geom) / NULLIF(count(*), 0), 1) AS geom_pct,
               count(region_code) AS with_region,
               round(100.0 * count(region_code) / NULLIF(count(*), 0), 1) AS region_pct
        FROM complex
    """),
    ("좌표 출처·신뢰도 (NULL 출처 = 미검증 레거시 좌표 — 0이어야 정상)", """
        SELECT coalesce(geom_source, '(출처없음)') AS geom_source,
               coalesce(geom_confidence, '(미검증)') AS confidence,
               count(*) AS complexes
        FROM complex WHERE geom IS NOT NULL
        GROUP BY 1, 2 ORDER BY 3 DESC
    """),
    ("⚠️ 좌표 충돌 — 확보율이 덮는 결함 (crossdong_rows·reb_conflict_rows 는 0이어야 정상)", """
        WITH pts AS (
            SELECT id, name, address_jibun, reb_complex_id, ST_AsText(geom) AS wkt
            FROM complex WHERE geom IS NOT NULL
        ), grp AS (
            SELECT wkt, count(*) AS n, count(DISTINCT address_jibun) AS dongs,
                   count(DISTINCT reb_complex_id) AS rebs
            FROM pts GROUP BY wkt HAVING count(*) > 1
        )
        SELECT
            (SELECT count(*) FROM pts) AS with_geom,
            (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt) AS collision_rows,
            (SELECT round(100.0 * count(*) / NULLIF((SELECT count(*) FROM pts), 0), 1)
             FROM pts p JOIN grp g ON g.wkt = p.wkt) AS collision_pct,
            (SELECT count(*) FROM grp) AS collision_points,
            (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt WHERE g.dongs > 1)
                AS crossdong_rows,
            (SELECT count(*) FROM grp WHERE rebs > 1) AS reb_conflict_points,
            (SELECT count(*) FROM pts p JOIN grp g ON g.wkt = p.wkt WHERE g.rebs > 1)
                AS reb_conflict_rows
    """),
    ("⛔ 같은 점 · 다른 부동산원 단지 (CR-021 GEO-3 — 0이어야 정상)", """
        WITH pts AS (
            SELECT id, name, address_jibun, reb_complex_id, ST_AsText(geom) AS wkt
            FROM complex WHERE geom IS NOT NULL
        ), grp AS (
            SELECT wkt FROM pts
            GROUP BY wkt HAVING count(*) > 1 AND count(DISTINCT reb_complex_id) > 1
        )
        SELECT g.wkt,
               left(string_agg(p.address_jibun || ' ' || p.name || '[' ||
                               coalesce(p.reb_complex_id, '-') || ']',
                               ' / ' ORDER BY p.id), 140) AS members
        FROM grp g JOIN pts p ON p.wkt = g.wkt
        GROUP BY g.wkt ORDER BY g.wkt LIMIT 20
    """),
    ("좌표 충돌 상위 10 (같은 점을 쓰는 단지들)", """
        WITH pts AS (
            SELECT id, name, address_jibun, ST_AsText(geom) AS wkt
            FROM complex WHERE geom IS NOT NULL
        ), grp AS (
            SELECT wkt, count(*) AS n, count(DISTINCT address_jibun) AS dongs
            FROM pts GROUP BY wkt HAVING count(*) > 1
        )
        SELECT g.n AS complexes, g.dongs AS distinct_dongs,
               left(string_agg(p.address_jibun || ' ' || p.name, ' / ' ORDER BY p.id), 110)
                   AS members
        FROM grp g JOIN pts p ON p.wkt = g.wkt
        GROUP BY g.wkt, g.n, g.dongs
        ORDER BY g.dongs DESC, g.n DESC LIMIT 10
    """),
    ("부동산원 매칭 (REB-1) — 매칭 못 한 단지는 주소·동수를 모르는 단지다", """
        SELECT count(*) AS complexes,
               count(reb_complex_id) AS matched,
               round(100.0 * count(reb_complex_id) / NULLIF(count(*), 0), 1) AS matched_pct,
               count(total_buildings) AS with_dong_count,
               count(total_households) AS with_households,
               count(built_year) AS with_built_year
        FROM complex
    """),
    ("동(棟) 정보 — '몇 개인지 안다' 와 '무엇인지 안다' 는 다르다", """
        SELECT
            (SELECT count(*) FROM complex WHERE total_buildings IS NOT NULL)
                AS dong_count_known,
            (SELECT count(DISTINCT complex_id) FROM building) AS dong_list_known,
            (SELECT count(*) FROM building) AS building_rows,
            (SELECT count(DISTINCT complex_id) FROM trade WHERE apt_dong IS NOT NULL)
                AS dong_measured,
            (SELECT count(*) FROM (
                SELECT complex_id FROM building GROUP BY 1
                INTERSECT
                SELECT complex_id FROM trade WHERE apt_dong IS NOT NULL GROUP BY 1) x)
                AS both
    """),
    ("F4 동별 실측 커버리지 상위 10 (아는 동 대비 측정한 동)", """
        SELECT c.name, c.address_jibun,
               count(DISTINCT b.name) AS known_dongs,
               count(DISTINCT t.apt_dong) AS measured_dongs
        FROM complex c
        JOIN building b ON b.complex_id = c.id
        LEFT JOIN trade t ON t.complex_id = c.id AND t.apt_dong IS NOT NULL
        GROUP BY c.id, c.name, c.address_jibun
        HAVING count(DISTINCT t.apt_dong) > 0
        ORDER BY known_dongs DESC, measured_dongs DESC LIMIT 10
    """),
    ("중복 의심 (자연키 2행 이상 — 0이어야 정상)", """
        SELECT count(*) AS dup_groups FROM (
            SELECT complex_id, contract_date, price_krw, area_m2, floor
            FROM trade GROUP BY 1,2,3,4,5 HAVING count(*) > 1
        ) d
    """),
    ("단지당 거래 상위 10 (F4 표본 확인)", """
        SELECT c.name, count(*) AS trades, count(DISTINCT t.apt_dong) AS dongs,
               count(t.apt_dong) AS with_dong
        FROM trade t JOIN complex c ON c.id = t.complex_id
        WHERE NOT t.is_cancelled
        GROUP BY c.id, c.name ORDER BY trades DESC LIMIT 10
    """),
]


def main() -> int:
    from sqlalchemy import text

    load_env()
    url = database_url()
    engine = make_engine(url)
    print(f"[INFO] DB {safe_dsn(url)}\n")
    try:
        with engine.connect() as conn:
            for title, sql in QUERIES:
                print(f"── {title}")
                rows = conn.execute(text(sql)).mappings().all()
                if not rows:
                    print("   (없음)")
                else:
                    cols = list(rows[0].keys())
                    print("   " + " | ".join(cols))
                    for r in rows:
                        print("   " + " | ".join(str(r[c]) for c in cols))
                print()
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
