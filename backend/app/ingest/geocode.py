"""단지 좌표 확보 — 카카오 로컬 키워드 검색으로 단지명→좌표(WGS84).

왜 필요한가
-----------
MOLIT 실거래에는 좌표가 없다(normalize.py). 하지만 지도(F1)·입지 분석(F5)·동별 추정(F4)이
전부 complex.geom(POINT,4326) 위에서 돈다. 좌표 없는 단지는 지도에 못 찍고 입지 분석이
'정보 없음'이 된다(postgis.py 주석). 그래서 적재 후 **별도 단계**로 좌표를 채운다.

좌표 소스 조사 (ORDER 지시: 카카오 or 별도소스)
------------------------------------------------
| 후보 | 방식 | 판단 |
|---|---|---|
| **카카오 로컬 키워드검색** | "법정동 단지명" → 장소 좌표 | ✅ 채택. 단지명 기반이라 실거래명과 직결. REST 키 필요 |
| 카카오 주소검색 | 도로명/지번 주소 → 좌표 | MOLIT 에 정확한 번지가 없어 후순위 |
| 건축물대장 | 대장에 좌표가 있으면 사용 | 동별 좌표까지 가능하나 매칭 난이도↑ (2차) |
| 도로명주소 API(주소기반산업지원) | 주소→좌표 | 카카오 실패 시 폴백 |

⚠️ 키·합법성
-----------
- KAKAO_REST_API_KEY 는 사람이 발급한다(.env). 없으면 NullGeocoder 로 동작(좌표 미확보).
- 카카오 로컬 API 는 개인·비상업 쿼터 내 사용. rate limit 준수(RateLimiter).
- 좌표를 못 찾으면 **추정하지 않고 None** — 틀린 좌표는 틀린 입지 분석을 낳는다.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.ingest import normalize
from app.ingest.ratelimit import RateLimiter

KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


class Geocoder(Protocol):
    def geocode(self, query: str) -> tuple[float, float] | None:
        """질의어 → (lon, lat) 또는 못 찾으면 None."""
        ...


class NullGeocoder:
    """좌표를 확보하지 않는다(키 미발급 등). 항상 None — 도메인이 '정보 없음' 처리."""

    def geocode(self, query: str) -> tuple[float, float] | None:
        return None


def build_query(key: normalize.ComplexKey) -> str:
    """단지 키 → 카카오 키워드 질의. '법정동 단지명'이 매칭률이 가장 높다."""
    parts = [p for p in (key.legal_dong, key.name) if p]
    return " ".join(parts).strip()


#: (url, headers, params) → 파싱된 JSON dict. 테스트에서 네트워크 없이 주입한다.
HttpGet = Callable[[str, dict[str, str], dict[str, str]], dict[str, Any]]


def _httpx_get(url: str, headers: dict[str, str], params: dict[str, str]) -> dict[str, Any]:
    import httpx

    resp = httpx.get(url, headers=headers, params=params, timeout=20.0)
    resp.raise_for_status()
    return resp.json()


class KakaoGeocoder:
    """카카오 로컬 키워드 검색 기반 지오코더.

    좌표는 x=경도(lon), y=위도(lat) 로 온다 — 순서를 뒤집으면 지도에서 바다에 찍힌다.
    """

    def __init__(self, rest_api_key: str, *,
                 http_get: HttpGet = _httpx_get,
                 rate_limiter: RateLimiter | None = None) -> None:
        if not rest_api_key:
            raise ValueError("KAKAO_REST_API_KEY 가 필요합니다")
        self._key = rest_api_key
        self._get = http_get
        self._limiter = rate_limiter or RateLimiter(min_interval_sec=0.3, jitter_sec=0.2)

    def geocode(self, query: str) -> tuple[float, float] | None:
        if not query.strip():
            return None
        self._limiter.wait()                       # rate limit — 카카오 쿼터·차단 회피
        headers = {"Authorization": f"KakaoAK {self._key}"}
        data = self._get(KAKAO_KEYWORD_URL, headers, {"query": query, "size": "1"})
        docs = data.get("documents") or []
        if not docs:
            return None
        top = docs[0]
        try:
            return (float(top["x"]), float(top["y"]))   # (lon, lat)
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class GeocodeResult:
    resolved: int = 0
    unresolved: int = 0


def enrich_geom(
    candidates: Iterable[tuple[int, str]],
    geocoder: Geocoder,
    update: Callable[[int, float, float], None],
) -> GeocodeResult:
    """(complex_id, query) 후보들을 지오코딩해 update(complex_id, lon, lat) 로 반영한다.

    DB 와 무관하게(주입식) 동작해 테스트가 네트워크·DB 없이 로직을 검증한다.
    못 찾은 건 조용히 넘기지 않고 unresolved 로 센다(재시도·조사 대상).
    """
    result = GeocodeResult()
    for complex_id, query in candidates:
        coords = geocoder.geocode(query)
        if coords is None:
            result.unresolved += 1
            continue
        lon, lat = coords
        update(complex_id, lon, lat)
        result.resolved += 1
    return result


def enrich_postgis_geom(engine: Any, geocoder: Geocoder, *, limit: int = 500) -> GeocodeResult:
    """geom 이 NULL 인 단지를 찾아 지오코딩해 POINT(4326)로 채운다(실 DB용).

    ⚠️ 키·DB 준비 후 사용. 좌표는 ST_SetSRID(ST_MakePoint(lon, lat), 4326).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, address_jibun FROM complex
            WHERE geom IS NULL
            ORDER BY id LIMIT :limit
        """), {"limit": limit}).all()

    def _update(complex_id: int, lon: float, lat: float) -> None:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE complex
                SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), updated_at = now()
                WHERE id = :id
            """), {"id": complex_id, "lon": lon, "lat": lat})

    candidates = [
        (r.id, " ".join(p for p in (r.address_jibun, r.name) if p).strip())
        for r in rows
    ]
    return enrich_geom(candidates, geocoder, _update)
