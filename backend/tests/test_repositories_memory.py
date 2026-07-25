"""인메모리 리포지토리 — DB 없이 도는 계약 테스트.

PostGIS 구현과 **같은 Protocol** 을 만족하는지, 그리고 입지 스텁이
"모르는 건 모른다고 답하는지"를 본다. 실제 공간연산 검증은
`test_postgis_repo.py`(needs_db) 몫이다.
"""
from __future__ import annotations

import pytest

from app.domain.location.models import BuildingLocationFact, LocationFacts, StationFact
from app.repositories import base
from app.repositories.memory import InMemoryRepository

PROTOCOLS = (
    base.UserRepository, base.ProfileRepository, base.MapRepository,
    base.JobRepository, base.LocationRepository, base.RecommendationRepository,
)


@pytest.fixture()
def repo() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=lambda p: p.__name__)
def test_인메모리가_모든_Protocol을_만족한다(repo, protocol):
    assert isinstance(repo, protocol)


def test_입지_스텁은_넣은_사실만_돌려준다(repo):
    """좌표로 거리를 흉내 내지 않는다 — 가짜 거리로 통과한 로직은 실 DB 에서 처음 틀린다."""
    assert repo.location_facts(1) is None
    assert repo.building_location_facts(1) == []

    facts = LocationFacts(stations=(StationFact(name="선릉역", distance_m=180.0,
                                                lines=("2호선",)),))
    repo.set_location_facts(1, facts)
    assert repo.location_facts(1) is facts
    assert repo.location_facts(2) is None      # 다른 단지까지 새지 않는다


def test_동별_입지_스텁(repo):
    repo.set_building_location_facts(1, [
        BuildingLocationFact(building_id=101, label="101동", station_distance_m=200.0),
    ])
    got = repo.building_location_facts(1)
    assert [b.label for b in got] == ["101동"]

    # 돌려준 목록을 밖에서 고쳐도 저장된 값이 흔들리지 않는다
    got.clear()
    assert len(repo.building_location_facts(1)) == 1


def test_get_job은_소유자_외에는_None(repo):
    """IDOR — PostGIS 구현과 같은 규약(security.md §2.2)."""
    owner = repo.create_user("a@example.com", "h")
    other = repo.create_user("b@example.com", "h")
    repo.create_job("rec_1", owner.id, {})
    assert repo.get_job("rec_1", owner.id) is not None
    assert repo.get_job("rec_1", other.id) is None
