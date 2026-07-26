/**
 * 수도권 시군구 목록 — AI 추천의 **분석 지역**을 고르기 위한 것.
 *
 * 어디서 왔나
 * -----------
 * `config/regions_capital.yaml`(행정안전부 법정동코드 전체자료에서 자동 생성, as_of 2026-07-25)를
 * 그대로 옮겼다. 5자리 코드는 국토교통부 실거래가 API 의 LAWD_CD 이자,
 * 서버 `recommendation_candidates(region_codes=[...])` 가 **접두 매칭**으로 쓰는 값이다.
 *
 * ⚠️ 한계 — 이 목록은 **행정구역 기준**이지 "데이터가 있는 지역" 목록이 아니다.
 *    수집이 끝나지 않은 시군구를 고르면 후보가 0건일 수 있다. 서버에 "데이터 있는 시군구"를
 *    돌려주는 엔드포인트가 없어서 지금은 이 방식뿐이다(PM 보고 항목).
 *    화면은 이 사실을 숨기지 않는다 — RegionPicker 가 안내 문구로 함께 보여준다.
 *    엔드포인트가 생기면 **이 파일만** 서버 조회로 바꾸면 된다(호출부는 그대로).
 */

export interface Region {
  /** 5자리 시군구 코드(LAWD_CD). 서버는 complex.region_code(10자리)와 접두 매칭한다. */
  code: string;
  sido: "서울" | "경기" | "인천";
  name: string;
}

/** 생성 원본의 기준일. 화면에 함께 노출해 "언제 기준 목록인지" 알 수 있게 한다. */
export const REGIONS_AS_OF = "2026-07-25";

export const REGIONS: Region[] = [
  { code: "11110", sido: "서울", name: "종로구" },
  { code: "11140", sido: "서울", name: "중구" },
  { code: "11170", sido: "서울", name: "용산구" },
  { code: "11200", sido: "서울", name: "성동구" },
  { code: "11215", sido: "서울", name: "광진구" },
  { code: "11230", sido: "서울", name: "동대문구" },
  { code: "11260", sido: "서울", name: "중랑구" },
  { code: "11290", sido: "서울", name: "성북구" },
  { code: "11305", sido: "서울", name: "강북구" },
  { code: "11320", sido: "서울", name: "도봉구" },
  { code: "11350", sido: "서울", name: "노원구" },
  { code: "11380", sido: "서울", name: "은평구" },
  { code: "11410", sido: "서울", name: "서대문구" },
  { code: "11440", sido: "서울", name: "마포구" },
  { code: "11470", sido: "서울", name: "양천구" },
  { code: "11500", sido: "서울", name: "강서구" },
  { code: "11530", sido: "서울", name: "구로구" },
  { code: "11545", sido: "서울", name: "금천구" },
  { code: "11560", sido: "서울", name: "영등포구" },
  { code: "11590", sido: "서울", name: "동작구" },
  { code: "11620", sido: "서울", name: "관악구" },
  { code: "11650", sido: "서울", name: "서초구" },
  { code: "11680", sido: "서울", name: "강남구" },
  { code: "11710", sido: "서울", name: "송파구" },
  { code: "11740", sido: "서울", name: "강동구" },
  { code: "28125", sido: "인천", name: "제물포구" },
  { code: "28155", sido: "인천", name: "영종구" },
  { code: "28177", sido: "인천", name: "미추홀구" },
  { code: "28185", sido: "인천", name: "연수구" },
  { code: "28200", sido: "인천", name: "남동구" },
  { code: "28237", sido: "인천", name: "부평구" },
  { code: "28245", sido: "인천", name: "계양구" },
  { code: "28275", sido: "인천", name: "서해구" },
  { code: "28290", sido: "인천", name: "검단구" },
  { code: "28710", sido: "인천", name: "강화군" },
  { code: "28720", sido: "인천", name: "옹진군" },
  { code: "41110", sido: "경기", name: "수원시" },
  { code: "41111", sido: "경기", name: "수원시 장안구" },
  { code: "41113", sido: "경기", name: "수원시 권선구" },
  { code: "41115", sido: "경기", name: "수원시 팔달구" },
  { code: "41117", sido: "경기", name: "수원시 영통구" },
  { code: "41130", sido: "경기", name: "성남시" },
  { code: "41131", sido: "경기", name: "성남시 수정구" },
  { code: "41133", sido: "경기", name: "성남시 중원구" },
  { code: "41135", sido: "경기", name: "성남시 분당구" },
  { code: "41150", sido: "경기", name: "의정부시" },
  { code: "41170", sido: "경기", name: "안양시" },
  { code: "41171", sido: "경기", name: "안양시 만안구" },
  { code: "41173", sido: "경기", name: "안양시 동안구" },
  { code: "41190", sido: "경기", name: "부천시" },
  { code: "41192", sido: "경기", name: "부천시 원미구" },
  { code: "41194", sido: "경기", name: "부천시 소사구" },
  { code: "41196", sido: "경기", name: "부천시 오정구" },
  { code: "41210", sido: "경기", name: "광명시" },
  { code: "41220", sido: "경기", name: "평택시" },
  { code: "41250", sido: "경기", name: "동두천시" },
  { code: "41270", sido: "경기", name: "안산시" },
  { code: "41271", sido: "경기", name: "안산시 상록구" },
  { code: "41273", sido: "경기", name: "안산시 단원구" },
  { code: "41280", sido: "경기", name: "고양시" },
  { code: "41281", sido: "경기", name: "고양시 덕양구" },
  { code: "41285", sido: "경기", name: "고양시 일산동구" },
  { code: "41287", sido: "경기", name: "고양시 일산서구" },
  { code: "41290", sido: "경기", name: "과천시" },
  { code: "41310", sido: "경기", name: "구리시" },
  { code: "41360", sido: "경기", name: "남양주시" },
  { code: "41370", sido: "경기", name: "오산시" },
  { code: "41390", sido: "경기", name: "시흥시" },
  { code: "41410", sido: "경기", name: "군포시" },
  { code: "41430", sido: "경기", name: "의왕시" },
  { code: "41450", sido: "경기", name: "하남시" },
  { code: "41460", sido: "경기", name: "용인시" },
  { code: "41461", sido: "경기", name: "용인시 처인구" },
  { code: "41463", sido: "경기", name: "용인시 기흥구" },
  { code: "41465", sido: "경기", name: "용인시 수지구" },
  { code: "41480", sido: "경기", name: "파주시" },
  { code: "41500", sido: "경기", name: "이천시" },
  { code: "41550", sido: "경기", name: "안성시" },
  { code: "41570", sido: "경기", name: "김포시" },
  { code: "41590", sido: "경기", name: "화성시" },
  { code: "41591", sido: "경기", name: "화성시 만세구" },
  { code: "41593", sido: "경기", name: "화성시 효행구" },
  { code: "41595", sido: "경기", name: "화성시 병점구" },
  { code: "41597", sido: "경기", name: "화성시 동탄구" },
  { code: "41610", sido: "경기", name: "광주시" },
  { code: "41630", sido: "경기", name: "양주시" },
  { code: "41650", sido: "경기", name: "포천시" },
  { code: "41670", sido: "경기", name: "여주시" },
  { code: "41800", sido: "경기", name: "연천군" },
  { code: "41820", sido: "경기", name: "가평군" },
  { code: "41830", sido: "경기", name: "양평군" },
];

export const SIDO_ORDER: Array<Region["sido"]> = ["서울", "경기", "인천"];

/** 코드 → 지역. 선택 칩을 그릴 때 이름을 되찾는 용도. */
const BY_CODE = new Map(REGIONS.map((r) => [r.code, r]));

export function regionByCode(code: string): Region | undefined {
  return BY_CODE.get(code);
}

/** 화면에 보여줄 이름 — 시도까지 붙여야 "중구"가 서울인지 인천인지 구분된다. */
export function regionLabel(region: Region): string {
  return `${region.sido} ${region.name}`;
}

/**
 * 검색 — 두 가지 방식을 함께 쓴다.
 *
 *  ① **토큰 AND**: 공백으로 끊어 **모든 조각**이 들어 있으면 통과.
 *     "성남 분당" → 성남시 분당구 (이름 중간에 '시'가 끼어 있어도 걸린다)
 *  ② **공백 제거 부분일치**: "서울강남" → 서울 강남구
 *
 * ①만 있으면 붙여 쓴 검색이 안 되고, ②만 있으면 띄어 쓴 검색이 안 된다.
 * (실제로 ②만 있던 첫 구현에서 "성남 분당"이 0건이었다 — 테스트가 잡았다.)
 * 초성 검색까지는 하지 않는다(구현 비용 대비 이득이 작고, 목록이 91개뿐이다).
 */
export function searchRegions(query: string, source: Region[] = REGIONS): Region[] {
  const tokens = query.trim().split(/\s+/).filter((t) => t !== "");
  if (tokens.length === 0) return source;
  const joined = tokens.join("");

  return source.filter((r) => {
    const target = `${r.sido}${r.name}`;
    const squeezed = target.replace(/\s+/g, "");
    if (squeezed.includes(joined)) return true;
    return tokens.every((t) => squeezed.includes(t));
  });
}
