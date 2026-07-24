"""리포지토리 선택 — 설정에 따라 PostGIS 또는 인메모리.

원칙(core/config.py 와 같다): **조용히 약한 상태로 돌아가지 않는다.**
DB 설정이 없는데 운영으로 뜨면 인메모리로 도는 대신 **기동을 막는다.**
재시작마다 사용자 자산 정보가 사라지는 서버가 "정상 기동"으로 보이는 게
설정 오류로 안 뜨는 것보다 훨씬 위험하다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("app.repositories")


def build_repository(settings):
    """`APP_ROLE`(api/worker-*) 과 무관하게 DB 설정이 있으면 PostGIS 를 쓴다.

    워커도 같은 DB 를 본다. 갈리는 기준은 역할이 아니라 **DB 설정의 유무**다.
    """
    if settings.postgres_user and settings.postgres_password:
        from app.repositories.postgis import PostgisRepository, create_db_engine

        logger.info(
            "PostGIS 리포지토리로 기동합니다 (role=%s, db=%s@%s:%s/%s)",
            settings.app_role, settings.postgres_user, settings.postgres_host,
            settings.postgres_port, settings.postgres_db,
        )
        return PostgisRepository(create_db_engine(settings))

    if settings.debug:
        from app.repositories.memory import InMemoryRepository

        logger.warning(
            "DB 설정이 없어 인메모리 리포지토리로 기동합니다 (DEBUG=true). "
            "재시작하면 데이터가 사라집니다 — 개발 전용입니다."
        )
        return InMemoryRepository()

    raise RuntimeError(
        "POSTGRES_USER / POSTGRES_PASSWORD 가 비어 있어 DB 에 연결할 수 없습니다. "
        ".env 를 채우세요. 개발 중이라면 DEBUG=true 로 두면 인메모리로 기동합니다."
    )
