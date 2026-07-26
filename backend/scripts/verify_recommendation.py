"""추천 파이프라인 실데이터 검증 — 사용자 → 프로필 → 예산 → 추천까지 끝까지 돌린다.

왜 이 스크립트가 있나
---------------------
단위 테스트는 픽스처로 돈다. 픽스처는 항상 "필요한 데이터가 다 있는" 세계다.
실데이터에서는 **비는 쪽이 정상**이라, 결과가 0건일 때 "왜 0건인지"를 못 대면
제품이 조용히 죽는다. 그래서 여기서는 결과와 함께 **깔때기(funnel)** 를 두 겹으로 찍는다:

    (DB)  지역 단지 → 좌표 보유 → 활성 호가 → 실거래 표본 5건+ → 가격 근거 → 예산 이내
    (런타임) 후보 조립(호가기준/실거래기준) → 파이프라인 제외 사유 → 최종 추천

각 단계에서 몇 개가 떨어졌는지 보이면 "그냥 안 나온다"가 아니라
"표본 부족" / "예산 초과" / "가격 근거 없음" 으로 말할 수 있다.

⚠️ 호가 0건은 더 이상 치명적이지 않다 (CHARTER G4)
--------------------------------------------------
공공 오픈API 에는 호가가 없어 `listing` 테이블은 보통 **0건**이다. 예전 러너는 호가
없는 단지를 건너뛰어 후보가 구조적으로 항상 0건이었다. 지금은 실거래로 후보를 세우되
`price_basis="trade"` 로 **호가가 아님을 명시**한다. 그래서 이 깔때기의 "활성 호가"
줄은 이제 실패 지점이 아니라 **어느 경로로 후보가 섰는지**를 알려 주는 줄이다.

F4 검증
-------
동별 실측(`dong_valuation`)은 추천 아이템 안에만 들어 있어, 추천이 0건이면 확인이 안 된다.
그래서 실거래만으로 `dong_effect` 를 **직접** 돌려 available/basis 를 따로 찍는다.

⚠️ 이 스크립트는 검증용 사용자를 만든다(기본 `--email`).

비밀번호 (SR17-2)
-----------------
예전에는 비밀번호가 **소스에 상수로 박혀** 있었다. 이 저장소의 origin 은 공개
저장소라, 그대로 커밋됐다면 운영 DB 에 살아 있는 계정의 **동작하는 자격증명**을
공개하는 것이었다(CWE-798). 지금은 소스에 비밀번호가 없다:

  · 기본: 실행할 때마다 `secrets.token_urlsafe` 로 **1회용** 비밀번호를 만든다.
    프로세스 밖으로 나가지 않으며 화면에도 찍지 않는다.
  · 필요하면 `VERIFY_TEST_PASSWORD` 환경변수로 넘긴다(로그인 흐름까지 볼 때).

뒷정리
------
검증 계정은 **기본적으로 실행 끝에 지운다**(`user_profile`·`recommendation_job` 은
FK CASCADE). 남겨 두면 운영 DB 에 로그인 가능한 계정이 계속 쌓인다.
안전장치: `.invalid` 로 끝나는 주소(RFC 2606 예약 TLD)만 지운다 — 실사용자 주소를
넘겨도 파괴적 작업이 일어나지 않는다. 남기려면 `--keep-user`.

사용
----
    export DATABASE_URL=...
    python scripts/verify_recommendation.py --region 11680 --cash 800000000 --income 120000000
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import secrets
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 로깅 억제·마스킹을 설치한다(SR17-3). 지우지 말 것.
from _common import configure_logging, load_env, make_engine  # noqa: E402

from app.agents.recommend import run_recommendation_job  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import encrypt_amount, hash_password, load_key  # noqa: E402
from app.domain.affordability.engine import compute_affordability  # noqa: E402
from app.domain.affordability.models import Borrower, PropertyFacts  # noqa: E402
from app.domain.rules.loader import load_rules  # noqa: E402
from app.domain.valuation.stats import dong_effect, fair_price_band  # noqa: E402
from app.repositories.base import ProfileRecord  # noqa: E402
from app.repositories.postgis import PostgisRepository  # noqa: E402

#: 환경변수로 비밀번호를 넘기고 싶을 때 쓰는 이름(로그인 흐름까지 손으로 볼 때).
PASSWORD_ENV = "VERIFY_TEST_PASSWORD"

#: 자동 정리를 허용하는 주소 꼬리. RFC 2606 이 예약한 `.invalid` 는 실제로 존재할 수
#: 없는 TLD 다 — 실사용자 계정을 실수로 지우는 경로를 문법으로 막는다.
DISPOSABLE_EMAIL_SUFFIX = ".invalid"


def make_test_password() -> str:
    """검증 계정 비밀번호를 **실행 시점에** 만든다. 소스에 상수로 두지 않는다(SR17-2).

    `VERIFY_TEST_PASSWORD` 가 있으면 그 값을, 없으면 1회용 난수를 쓴다.
    돌려준 값은 화면·로그 어디에도 찍지 않는다.
    """
    from_env = os.getenv(PASSWORD_ENV, "").strip()
    if from_env:
        return from_env
    # 대/소문자·숫자·기호 요건이 있는 정책에도 걸리지 않게 접두사를 붙인다.
    return "Vr1!" + secrets.token_urlsafe(24)


def ensure_user(repo, email: str, password: str):
    user = repo.get_user_by_email(email)
    if user is not None:
        return user, False
    return repo.create_user(email, hash_password(password)), True


def purge_user(engine, email: str) -> dict[str, int]:
    """검증 계정과 딸린 행을 지운다. `.invalid` 주소가 아니면 **거부**한다.

    `user_profile`·`user_preference`·`recommendation_job`(→`recommendation_item`)
    은 FK 가 ON DELETE CASCADE 라 app_user 한 행을 지우면 함께 사라진다.
    지우기 전에 무엇을 지우는지 세어서 돌려준다(조용한 삭제 금지).
    """
    from sqlalchemy import text

    if not email.endswith(DISPOSABLE_EMAIL_SUFFIX):
        raise SystemExit(
            f"[FAIL] 자동 정리는 {DISPOSABLE_EMAIL_SUFFIX} 주소만 허용합니다: {email}\n"
            "       실사용자 계정을 지우지 않기 위한 안전장치입니다. --keep-user 를 쓰세요.")

    counted = {"app_user": 0, "user_profile": 0, "user_preference": 0,
               "recommendation_job": 0, "recommendation_item": 0}
    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM app_user WHERE email = :e"),
                           {"e": email}).first()
        if row is None:
            return counted
        uid = row.id
        for table, query in (
            ("user_profile", "SELECT count(*) FROM user_profile WHERE user_id = :u"),
            ("user_preference", "SELECT count(*) FROM user_preference WHERE user_id = :u"),
            ("recommendation_job", "SELECT count(*) FROM recommendation_job WHERE user_id = :u"),
            ("recommendation_item",
             "SELECT count(*) FROM recommendation_item i "
             "JOIN recommendation_job j ON j.id = i.job_id WHERE j.user_id = :u"),
        ):
            counted[table] = int(conn.execute(text(query), {"u": uid}).scalar_one())
        counted["app_user"] = conn.execute(
            text("DELETE FROM app_user WHERE id = :u"), {"u": uid}).rowcount
    return counted


def _check_persisted_columns(engine, job_id: str, expected: int) -> None:
    """정규화 컬럼이 실제로 채워졌는지 DB 에서 직접 확인한다.

    `recommendation_item.est_price_krw` 는 예전에 `item["ask_price_krw"]` 로 채워졌다.
    실거래 기준 후보는 호가가 없어(None) 그대로 두면 **컬럼이 통째로 NULL** 이 된다 —
    payload 에는 값이 있어서 API 응답만 보면 멀쩡해 보이고, 컬럼으로 조회·집계하는
    쪽에서만 조용히 비어 있게 된다. 그 침묵을 여기서 깬다.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT count(*) AS n,
                   count(est_price_krw) AS with_price,
                   count(*) FILTER (WHERE payload->>'price_basis' IS NOT NULL)
                       AS with_basis
            FROM recommendation_item WHERE job_id = :job_id
        """), {"job_id": job_id}).one()

    ok = row.n == expected and row.with_price == row.n and row.with_basis == row.n
    print(f"    DB 컬럼 검사: item {row.n}행 · est_price_krw {row.with_price}"
          f" · payload.price_basis {row.with_basis} "
          + ("✔" if ok else "← **불일치**"))


def funnel(engine, region_codes: list[str], budget: int | None) -> dict:
    """추천이 0건일 때 **어디서 떨어졌는지** 보여 준다(DB 레벨).

    실거래 창은 적정가 밴드의 마지막 사다리(36개월)와 맞춘다 — 그보다 오래된 거래는
    밴드가 쓰지 않으므로 "가격 근거 있음"으로 세면 사실과 다르다.
    예산 비교값도 파이프라인이 실제로 쓰는 값(중위)과 맞춘다. 최고가로 비교하면
    실제로는 살 수 있는 단지가 예산 초과로 잡혀 깔때기가 거짓말을 한다.
    """
    from sqlalchemy import text

    like = [f"{c}%" for c in region_codes] or ["%"]
    with engine.connect() as conn:
        rows = conn.execute(text("""
            WITH scoped AS (
                SELECT c.id, c.name, c.geom IS NOT NULL AS has_geom
                FROM complex c
                WHERE EXISTS (SELECT 1 FROM unnest(CAST(:pats AS text[])) p
                              WHERE c.region_code LIKE p)
            ), agg AS (
                SELECT s.id, s.name, s.has_geom,
                       (SELECT count(*) FROM listing li
                         WHERE li.complex_id = s.id AND li.status = 'active') AS listings,
                       (SELECT count(*) FROM trade tr
                         WHERE tr.complex_id = s.id AND NOT tr.is_cancelled
                           AND tr.contract_date >= current_date - 1096) AS trades_36m,
                       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY tr.price_krw)
                          FROM trade tr
                         WHERE tr.complex_id = s.id AND NOT tr.is_cancelled
                           AND tr.contract_date >= current_date - 1096) AS median_36m
                FROM scoped s
            )
            SELECT count(*) AS complexes,
                   count(*) FILTER (WHERE has_geom) AS with_geom,
                   count(*) FILTER (WHERE listings > 0) AS with_listings,
                   count(*) FILTER (WHERE trades_36m >= 5) AS with_trade_sample,
                   count(*) FILTER (WHERE listings > 0 OR trades_36m >= 5)
                       AS with_price_evidence,
                   count(*) FILTER (WHERE median_36m IS NOT NULL
                                      AND median_36m <= CAST(:budget AS bigint))
                       AS in_budget
            FROM agg
        """), {"pats": like, "budget": budget or 10**15}).one()

    print("── 후보 깔때기 (DB)")
    print(f"   지역 내 단지                 : {rows.complexes}")
    print(f"   좌표(geom) 보유              : {rows.with_geom}")
    print(f"   활성 호가(listing) 보유      : {rows.with_listings}"
          + ("   ← 공공API 에는 호가가 없다. 0 이어도 실거래로 후보가 선다(G4)"
             if rows.with_listings == 0 else ""))
    print(f"   실거래 36개월 5건 이상       : {rows.with_trade_sample}")
    print(f"   가격 근거 있음(호가 OR 실거래): {rows.with_price_evidence}"
          + ("   ← 0 이면 추천이 0건인 직접 원인"
             if rows.with_price_evidence == 0 else ""))
    print(f"   실거래 중위 ≤ 예산           : {rows.in_budget}")
    return {"complexes": rows.complexes, "with_geom": rows.with_geom,
            "with_listings": rows.with_listings,
            "with_trade_sample": rows.with_trade_sample,
            "with_price_evidence": rows.with_price_evidence,
            "in_budget": rows.in_budget}


#: 제외 사유 문구 → 보고용 버킷. 파이프라인이 남기는 사유는 사람이 읽는 문장이라
#: 그대로 세면 단지 이름·금액 때문에 전부 유니크해진다.
_EXCLUSION_BUCKETS = (("가격 근거 없음", "가격 근거 없음"), ("예산 초과", "예산 초과"))


def runtime_funnel(repo, criteria: dict, afford, top_n: int = 10) -> dict:
    """러너가 **실제로 조립한 후보**와 파이프라인이 떨어뜨린 사유를 센다.

    DB 깔때기는 "가능성"을 보여 주고, 이건 "실제로 무엇이 후보가 됐고 왜 떨어졌는지"를
    보여 준다. 둘이 어긋나면(예: 가격 근거 212개인데 후보 0개) 러너 쪽 버그다.

    ⚠️ `llm=None` 으로 돌린다 — 검증 때문에 외부로 나가는 호출을 만들지 않는다.
       (그래서 tripwire 도 불필요하다: 전송 경로 자체가 없다.)
    """
    # 러너 내부 함수를 직접 부른다 — 조립·제외 단계를 있는 그대로 보기 위해서.
    from app.agents.orchestrator import AnalysisContext, run_mvp_pipeline
    from app.agents.recommend import CANDIDATE_COMPLEX_LIMIT, _assemble_candidates

    cands = _assemble_candidates(repo, criteria, afford.max_purchase_krw)
    by_basis: dict[str, int] = {}
    for c in cands:
        by_basis[c.price_basis] = by_basis.get(c.price_basis, 0) + 1

    out = run_mvp_pipeline(
        AnalysisContext(affordability=afford, candidates=cands), llm=None, top_n=top_n)

    buckets: dict[str, int] = {}
    for e in out["excluded"]:
        reason = e.get("reason") or ""
        label = next((name for key, name in _EXCLUSION_BUCKETS if key in reason), "기타")
        buckets[label] = buckets.get(label, 0) + 1

    analysed = len(cands) - len(out["excluded"])
    print("\n── 후보 깔때기 (런타임)")
    print(f"   조회 단지 상한               : {CANDIDATE_COMPLEX_LIMIT}")
    print(f"   조립된 후보                  : {len(cands)}"
          f"  (호가기준 {by_basis.get('listing', 0)} · "
          f"실거래기준 {by_basis.get('trade', 0)})")
    print(f"   제외                         : {len(out['excluded'])}"
          f"  {json.dumps(buckets, ensure_ascii=False)}")
    print(f"   분석 통과                    : {analysed}")
    print(f"   최종 추천(top_n={top_n})         : {len(out['items'])}")
    return {"candidates": len(cands), "by_basis": by_basis,
            "excluded": len(out["excluded"]), "exclusion_buckets": buckets,
            "analysed": analysed, "recommended": len(out["items"])}


def check_f4(repo, engine, region_codes: list[str], top: int) -> dict:
    """실거래만으로 F4(동별 실측)를 직접 검증한다 — 추천이 비어도 확인 가능하게."""
    from sqlalchemy import text

    like = [f"{c}%" for c in region_codes] or ["%"]
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.name, count(*) AS n
            FROM complex c JOIN trade t ON t.complex_id = c.id
            WHERE NOT t.is_cancelled
              AND EXISTS (SELECT 1 FROM unnest(CAST(:pats AS text[])) p
                          WHERE c.region_code LIKE p)
            GROUP BY c.id, c.name
            ORDER BY n DESC LIMIT CAST(:top AS int)
        """), {"pats": like, "top": top}).all()

    as_of = dt.date.today()
    summary = {"checked": 0, "available": 0, "methods": {}}
    print("\n── F4 동별 실측 (dong_valuation)")
    for r in rows:
        trades = repo.trades_for_complex(r.id)
        if not trades:
            continue
        # 표본이 가장 많은 면적대를 고른다(실제 추천도 면적 그룹 단위로 판단한다).
        areas: dict[float, int] = {}
        for t in trades:
            if not t.is_cancelled:
                areas[round(t.area_m2, 1)] = areas.get(round(t.area_m2, 1), 0) + 1
        if not areas:
            continue
        area = max(areas, key=lambda a: areas[a])
        band = fair_price_band(trades, area_m2=area, as_of=as_of)
        # ⚠️ **밴드 기간을 넘기지 않는다.** 예전 이 스크립트는 `months=band.period_months`
        #    를 넘겨 F4-1 회귀(등기 전 거래엔 aptDong 이 없어 6개월 창에서 동 정보가
        #    33~53% 로 떨어짐)를 그대로 재현했고, 그래서 **운영 경로는 10/10 인데 이 표는
        #    3/8** 이라고 보고했다. 검증 도구가 제품보다 나쁘게 보고하면 그건 검증이 아니다.
        #    운영과 똑같이 dong_effect 의 자체 창(DONG_PERIOD_MONTHS)을 쓴다.
        d = dong_effect(trades, area_m2=area, as_of=as_of)

        summary["checked"] += 1
        summary["methods"][d.method] = summary["methods"].get(d.method, 0) + 1
        band_months = band.period_months if band.available else "-"
        if d.available:
            summary["available"] += 1
            top_dong = d.dongs[0]
            print(f"   ✔ {r.name[:22]:<22} {area}㎡ | available=True basis=trade_measured "
                  f"| 동 {len(d.dongs)}개 · 동정보 {d.coverage_pct}% · "
                  f"동창 {d.period_months}개월(밴드 {band_months}개월)"
                  f" | 최고 {top_dong.dong}: {top_dong.vs_complex_pct:+.1f}%"
                  f" (표본 {top_dong.sample_size})")
        else:
            print(f"   ✗ {r.name[:22]:<22} {area}㎡ | available=False method={d.method}"
                  f" | {d.reason}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="추천 파이프라인 실데이터 검증")
    ap.add_argument("--email", default="verify+recommend@example.invalid")
    ap.add_argument("--region", default="11680", help="시군구 5자리(쉼표)")
    ap.add_argument("--cash", type=int, default=800_000_000)
    ap.add_argument("--income", type=int, default=120_000_000)
    ap.add_argument("--loan", type=int, default=0)
    ap.add_argument("--f4-top", type=int, default=8, help="F4 를 확인할 상위 단지 수")
    ap.add_argument("--keep-user", action="store_true",
                    help="검증 계정을 지우지 않고 남긴다(기본은 실행 끝에 삭제)")
    args = ap.parse_args(argv)

    configure_logging(logging.INFO)
    # 뒷정리 대상인지 **시작 전에** 판정한다. 다 돌린 뒤 finally 에서 거절하면
    # 계정만 남고 사람은 성공한 줄 안다.
    if not args.keep_user and not args.email.endswith(DISPOSABLE_EMAIL_SUFFIX):
        print(f"[FAIL] --email 은 {DISPOSABLE_EMAIL_SUFFIX} 로 끝나야 합니다(자동 정리 대상). "
              "실사용자 주소로 검증하려면 --keep-user 를 함께 주세요.")
        return 2

    load_env()
    settings = get_settings()
    engine = make_engine()
    repo = PostgisRepository(engine)
    region_codes = [c.strip() for c in args.region.split(",") if c.strip()]

    try:
        key = load_key(settings.field_encryption_key)
        # 비밀번호는 여기서 만들어지고 여기서 끝난다 — 소스에도, 화면에도 남기지 않는다.
        user, created = ensure_user(repo, args.email, make_test_password())
        print(f"[1] 사용자 id={user.id} ({'생성' if created else '기존'})")

        repo.upsert_profile(ProfileRecord(
            user_id=user.id,
            cash_krw_enc=encrypt_amount(args.cash, user_id=user.id, field="cash_krw", key=key),
            income_krw_enc=encrypt_amount(args.income, user_id=user.id,
                                          field="income_krw", key=key),
            existing_loan_krw_enc=encrypt_amount(args.loan, user_id=user.id,
                                                 field="existing_loan_krw", key=key),
            owned_houses=0, household_size=3,
        ))
        print("[2] 프로필 저장(암호문) 완료")

        rules = load_rules(settings.tax_rules_path)
        afford = compute_affordability(
            Borrower(cash_krw=args.cash, annual_income_krw=args.income,
                     existing_annual_repayment_krw=0, existing_annual_interest_krw=0,
                     owned_houses=0, household_size=3),
            rules, prop=PropertyFacts(purpose="live"))
        api = afford.to_api()
        breakdown = api.get("breakdown", {})
        print(f"[3] /affordability → 실구매가능 {afford.max_purchase_krw:,}원 "
              f"(자기자금 {breakdown.get('own_cash_krw', 0):,} + "
              f"대출 {breakdown.get('max_loan_krw', 0):,})")

        job_id = str(uuid.uuid4())
        criteria = {"region_codes": region_codes, "purpose": "live"}
        repo.create_job(job_id, user.id, criteria)
        run_recommendation_job(repo=repo, settings=settings, job_id=job_id,
                               user_id=user.id, criteria=criteria, llm=None)
        job = repo.get_job(job_id, user.id)
        print(f"[4] 추천 job={job_id[:8]} status={job.status} items={len(job.items)}")

        for it in job.items[:10]:
            dv = it.get("dong_valuation") or {}
            band = it.get("price_band") or {}
            price = it.get("est_price_krw")
            price_s = f"{price:,}원" if isinstance(price, int) else "미상"
            name = ((it.get("complex") or {}).get("name") or "?")[:20]
            print(f"    #{it.get('rank')} {name:<20}"
                  f" {(it.get('unit_type') or {}).get('area_m2')}㎡"
                  f" | basis={it.get('price_basis')} est={price_s}"
                  f" (추정={it.get('price_estimated')}) ask_gap={it.get('ask_gap_pct')}"
                  f" 표본={band.get('sample_size')} score={it.get('total_score')}"
                  f" | dong.available={dv.get('available')} basis={dv.get('basis')}")
        if not job.items:
            print("    → 추천 0건. 아래 깔때기에서 어느 단계에서 떨어졌는지 확인하세요.")

        # 계약 요약: 프론트가 보게 될 필드가 실제로 실렸는지 확인한다.
        by_basis: dict[str, int] = {}
        dong_ok = 0
        for it in job.items:
            by_basis[it.get("price_basis")] = by_basis.get(it.get("price_basis"), 0) + 1
            if (it.get("dong_valuation") or {}).get("available"):
                dong_ok += 1
        if job.items:
            pct = round(dong_ok / len(job.items) * 100, 1)
            print(f"    price_basis 분포 {json.dumps(by_basis, ensure_ascii=False)}"
                  f" · dong_valuation.available {dong_ok}/{len(job.items)} ({pct}%)")
            # 실거래 기준 후보에 호가·갭이 새어 들어가면 계약 위반이다.
            leaked = [it for it in job.items
                      if it.get("price_basis") == "trade"
                      and (it.get("ask_price_krw") is not None
                           or it.get("ask_gap_pct") is not None)]
            print("    계약 검사: 실거래 기준 후보에 호가/갭 유출 "
                  + ("없음 ✔" if not leaked else f"**{len(leaked)}건 — G2 위반**"))
            _check_persisted_columns(engine, job_id, len(job.items))

        print()
        funnel(engine, region_codes, afford.max_purchase_krw)
        runtime_funnel(repo, criteria, afford)
        summary = check_f4(repo, engine, region_codes, args.f4_top)
        print(f"\n   F4 요약: {summary['available']}/{summary['checked']} 단지에서 "
              f"available=True · method 분포 {json.dumps(summary['methods'], ensure_ascii=False)}")
    finally:
        # 뒷정리를 finally 에 둔다 — 중간에 깨져도 로그인 가능한 계정을 남기지 않는다.
        # ⚠️ 여기서 난 예외로 **원래 오류를 덮지 않는다.** 정리 실패는 크게 알리고 넘어간다
        #    (계정이 남았다는 사실이 조용히 묻히는 것이 가장 위험하다).
        if args.keep_user:
            print(f"\n[정리] --keep-user → 검증 계정({args.email})을 남깁니다. "
                  "운영 DB 에 남는 계정입니다 — 확인 후 직접 지우세요.")
        else:
            try:
                removed = purge_user(engine, args.email)
                print(f"\n[정리] 검증 계정 삭제: app_user {removed['app_user']}건 "
                      f"(user_profile {removed['user_profile']} · "
                      f"user_preference {removed['user_preference']} · "
                      f"recommendation_job {removed['recommendation_job']} · "
                      f"recommendation_item {removed['recommendation_item']} 동반 삭제)")
            except Exception as exc:             # noqa: BLE001 - 원래 오류를 덮지 않는다
                print(f"\n[FAIL] 검증 계정 정리 실패({type(exc).__name__}) — "
                      f"운영 DB 에 {args.email} 계정이 남아 있을 수 있습니다. 직접 확인하세요.")
        repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
