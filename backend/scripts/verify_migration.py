"""001_init.sql 실검증 스크립트 — 빈 DB 에 적용하고 결과를 사람이 읽을 로그로 찍는다.

로컬에 Docker 가 없어 마이그레이션이 오래 미검증 상태였다(implementation-plan.md §0).
DB 를 구할 수 있는 곳이면 어디서든 **한 줄로** 검증하고 로그를 남기려고 만든 스크립트다.

사용
----
    # 1) 빈 DB 준비 (예)
    docker run -d --name pg-test -e POSTGRES_PASSWORD=pw \
        -e POSTGRES_DB=realestate_test -p 55432:5432 postgis/postgis:16-3.4

    # 2) 검증
    set TEST_DATABASE_URL=postgresql+psycopg://postgres:pw@localhost:55432/realestate_test
    python scripts/verify_migration.py

⚠️ 대상 DB 의 `public` 스키마를 삭제하고 다시 만든다.
   DB 이름에 `test` 가 없으면 거부한다(운영 DB 사고 방지).
   `--keep` 를 주면 스키마를 지우지 않고 그대로 적용만 시도한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

#: 파일명 순서 = 적용 순서. 운영에서 docker-entrypoint-initdb.d 가 하는 것과 같다.
MIGRATIONS = sorted((BACKEND_DIR / "migrations").glob("[0-9]*.sql"))

CHECKS: list[tuple[str, str]] = [
    ("확장(postgis, citext)",
     "SELECT extname FROM pg_extension WHERE extname IN ('postgis','citext') ORDER BY 1"),
    ("테이블 수",
     "SELECT count(*)::text FROM pg_tables WHERE schemaname='public'"),
    ("GiST 공간 인덱스",
     """SELECT i.relname FROM pg_index x
        JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_am am ON am.oid = i.relam
        WHERE am.amname='gist' ORDER BY 1"""),
    ("trade 파티션",
     """SELECT c.relname FROM pg_inherits i
        JOIN pg_class c ON c.oid = i.inhrelid
        JOIN pg_class p ON p.oid = i.inhparent
        WHERE p.relname='trade' ORDER BY 1"""),
    ("CHECK 제약",
     """SELECT conrelid::regclass::text || '.' || conname
        FROM pg_constraint WHERE contype='c'
          AND connamespace='public'::regnamespace ORDER BY 1"""),
    ("UNIQUE 제약 (002 포함)",
     """SELECT conrelid::regclass::text || '.' || conname
        FROM pg_constraint WHERE contype='u'
          AND connamespace='public'::regnamespace ORDER BY 1"""),
    ("user_profile 컬럼(평문 금액 없어야 함)",
     """SELECT column_name || ':' || data_type FROM information_schema.columns
        WHERE table_name='user_profile' ORDER BY ordinal_position"""),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="001_init.sql 실검증")
    parser.add_argument("--keep", action="store_true",
                        help="public 스키마를 지우지 않고 적용만 시도한다")
    args = parser.parse_args(argv)

    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        print("[FAIL] TEST_DATABASE_URL 이 없습니다. 검증할 DB 를 지정하세요.")
        return 2

    dbname = url.rsplit("/", 1)[-1].split("?")[0]
    if not args.keep and "test" not in dbname.lower():
        print(f"[FAIL] 안전장치: DB 이름 '{dbname}' 에 'test' 가 없습니다. "
              "이 스크립트는 public 스키마를 삭제합니다.")
        return 2

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        print("[FAIL] SQLAlchemy 가 없습니다. pip install -r requirements.txt")
        return 2

    # 접속 정보를 로그에 남기지 않는다 — 비밀번호가 들어 있다.
    print(f"[INFO] 대상 DB: {dbname}")
    for path in MIGRATIONS:
        print(f"[INFO] 마이그레이션: {path.relative_to(BACKEND_DIR)}")
    if not MIGRATIONS:
        print("[FAIL] migrations/ 에 적용할 .sql 이 없습니다.")
        return 2

    engine = create_engine(url, pool_pre_ping=True)

    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            if not args.keep:
                conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
                conn.exec_driver_sql("CREATE SCHEMA public")
                print("[OK]   public 스키마 초기화")

            server = conn.execute(text("SELECT version()")).scalar_one()
            print(f"[INFO] {server.split(' on ')[0]}")

            for path in MIGRATIONS:
                conn.exec_driver_sql(path.read_text(encoding="utf-8"))
                print(f"[OK]   {path.name} 적용 성공")

            postgis_version = conn.execute(text("SELECT postgis_version()")).scalar_one()
            print(f"[INFO] PostGIS {postgis_version}")

            for label, query in CHECKS:
                rows = [str(r[0]) for r in conn.execute(text(query))]
                print(f"[OK]   {label}: {len(rows)}건")
                for r in rows:
                    print(f"         - {r}")

            # 파티션 라우팅이 실제로 도는지 한 번 넣어 본다.
            conn.exec_driver_sql("""
                INSERT INTO region (code, sido) VALUES ('1168010100', '서울');
                INSERT INTO complex (region_code, name, geom)
                VALUES ('1168010100', '검증단지',
                        ST_SetSRID(ST_MakePoint(127.05, 37.50), 4326));
                INSERT INTO trade (complex_id, contract_date, price_krw, source)
                SELECT id, DATE '2026-03-01', 1500000000, 'verify' FROM complex;
            """)
            part = conn.execute(text(
                "SELECT tableoid::regclass::text FROM trade")).scalar_one()
            print(f"[OK]   파티션 라우팅: 2026-03-01 → {part}")

            plan = "\n".join(r[0] for r in conn.execute(text("""
                EXPLAIN SELECT c.id FROM complex c
                WHERE c.geom && ST_MakeEnvelope(127.0, 37.4, 127.1, 37.6, 4326)
            """)))
            print(f"[INFO] bbox 플랜: {plan.splitlines()[0].strip()}")

            conn.exec_driver_sql(
                "TRUNCATE region, complex, trade RESTART IDENTITY CASCADE")
    except Exception as exc:                       # noqa: BLE001 - 로그가 목적
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1
    finally:
        engine.dispose()

    print("[DONE] 마이그레이션 실검증 완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
