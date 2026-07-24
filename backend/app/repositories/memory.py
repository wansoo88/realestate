"""인메모리 리포지토리 — 테스트·로컬 개발용.

PostGIS 구현이 준비되기 전까지 API 계약을 검증하는 데 쓴다.
공간 필터는 단순 bbox 비교로 대체한다(실제 구현은 GiST 인덱스 + `&&` 연산자).
"""
from __future__ import annotations

import itertools
from typing import Any

from app.repositories.base import (
    ComplexSummary,
    JobRecord,
    ProfileRecord,
    UserRecord,
)


class InMemoryRepository:
    """UserRepository · ProfileRepository · MapRepository · JobRepository 를 모두 구현."""

    def __init__(self) -> None:
        self._users: dict[int, UserRecord] = {}
        self._by_email: dict[str, int] = {}
        self._profiles: dict[int, ProfileRecord] = {}
        self._prefs: dict[int, dict[str, Any]] = {}
        self._complexes: list[ComplexSummary] = []
        self._jobs: dict[str, JobRecord] = {}
        self._ids = itertools.count(1)

    # -- 사용자 -----------------------------------------------------------
    def create_user(self, email: str, password_hash: str) -> UserRecord:
        key = email.strip().lower()
        if key in self._by_email:
            raise ValueError("이미 등록된 이메일입니다")
        user = UserRecord(id=next(self._ids), email=key, password_hash=password_hash)
        self._users[user.id] = user
        self._by_email[key] = user.id
        return user

    def get_user_by_email(self, email: str) -> UserRecord | None:
        uid = self._by_email.get(email.strip().lower())
        return self._users.get(uid) if uid else None

    def get_user(self, user_id: int) -> UserRecord | None:
        return self._users.get(user_id)

    # -- 프로필 -----------------------------------------------------------
    def get_profile(self, user_id: int) -> ProfileRecord | None:
        return self._profiles.get(user_id)

    def upsert_profile(self, profile: ProfileRecord) -> ProfileRecord:
        self._profiles[profile.user_id] = profile
        return profile

    def get_preferences(self, user_id: int) -> dict[str, Any]:
        return self._prefs.get(user_id, {"prefer": {}, "avoid": {}, "weights": {}})

    def set_preferences(self, user_id: int, prefs: dict[str, Any]) -> dict[str, Any]:
        self._prefs[user_id] = prefs
        return prefs

    # -- 지도 -------------------------------------------------------------
    def add_complex(self, c: ComplexSummary) -> ComplexSummary:
        self._complexes.append(c)
        return c

    def complexes_in_bbox(
        self, *, min_lon: float, min_lat: float, max_lon: float, max_lat: float,
        max_price_krw: int | None = None,
        area_min_m2: float | None = None,
        area_max_m2: float | None = None,
        built_after: int | None = None,
        limit: int = 500,
    ) -> list[ComplexSummary]:
        out: list[ComplexSummary] = []
        for c in self._complexes:
            if not (min_lon <= c.lon <= max_lon and min_lat <= c.lat <= max_lat):
                continue
            if built_after is not None and (c.built_year or 0) < built_after:
                continue
            # 예산 초과 단지는 **제외하지 않고** 호출부가 흐리게 표시하도록 그대로 넘긴다
            # (ux/README.md §4 — 왜 후보에 없는지 보이게 한다).
            out.append(c)
            if len(out) >= limit:
                break
        return out

    # -- 추천 작업 ---------------------------------------------------------
    def create_job(self, job_id: str, user_id: int, criteria: dict[str, Any]) -> JobRecord:
        job = JobRecord(id=job_id, user_id=user_id, criteria_snapshot=criteria)
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str, user_id: int) -> JobRecord | None:
        """소유권 검증을 리포지토리 안에서 강제한다 (IDOR 방지)."""
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job
