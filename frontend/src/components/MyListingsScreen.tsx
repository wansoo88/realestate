/**
 * 내 매물 — **직접 본 호가를 적는 화면** (api-spec §2.5 · CR35-2).
 *
 * 왜 이 화면이 있나
 * -----------------
 * 추천 가중치의 **31%(가격 축)** 가 통째로 비어 있었다. 공공 오픈API 에는 호가가 없고,
 * 포털 자동수집은 약관·확정판결로 하지 않기로 했다. 남은 합법적인 경로는 **사용자가
 * 네이버 부동산 등에서 직접 보고 옮겨 적는 것**뿐이다. 실측으로 호가 1건이 들어오면
 * 그 후보의 가격 축이 `no_signal` → `applied` 로 바뀌고 반영률이 20% → 68% 가 된다.
 *
 * 그동안 추천 결과는 "'내 매물'에서 직접 입력하시면 가격 축이 반영됩니다"라고 안내하면서
 * 정작 그 화면이 없었다. 이 파일이 그 화면이다.
 *
 * 이 화면이 반드시 지키는 것
 * --------------------------
 *  ① **`problems` 를 보여준다.** 201/200 이어도 서버는 "저장은 했지만 알아야 할 것"을
 *     함께 준다(₩/㎡ 이상·낡음·중복). 안 보여주면 검증의 절반이 사라진다.
 *  ② **출처는 서버가 준 `source_label` 을 그대로** 쓴다. 프론트가 만들지 않는다.
 *     그리고 공공 데이터(ComplexCard 의 굵은 검정 금액)와 **다른 모양**으로 그린다 —
 *     같은 모양으로 그리면 내가 손으로 친 숫자가 국토교통부 실거래가처럼 보인다.
 *  ③ **낡음은 결과와 함께** 말한다. 90일 초과는 계산에서 빠지고(서버 판정),
 *     그 사실과 **갱신 동선**이 같은 자리에 있어야 한다.
 *  ④ **삭제와 '추천에서만 빼기'를 구분**한다. 삭제는 되돌릴 수 없고, 상태 변경은 기록을 남긴다.
 *  ⑤ **"반영 가능"과 "반영됐다"를 구분**한다(CR35-7). 서버가 아는 것은 이 호가 한 건의
 *     자격뿐이고, 실제 반영은 그 단지가 추천 요청의 조건·후보 상한을 통과해야 한다.
 *     그 나머지 절반은 서버 `notes` 가 **상시로** 말하므로 목록에도 저장 직후에도 싣는다.
 *
 * 🔐 이 값들은 저장소·URL·로그 어디에도 쓰지 않는다(메모리 상태로만 다룬다).
 */
import { useCallback, useEffect, useState } from "react";
import type { UserListing } from "../api/client";
import { formatAsOf, formatKrw } from "../lib/format";
import type { MyListings, SaveOutcome } from "../hooks/useMyListings";
import {
  buildCreate,
  buildPatch,
  serverFieldErrors,
  sourceLabel,
  stalenessView,
  statusLabel,
  statusPatch,
  summaryText,
  type ListingErrors,
  type ListingFormValues,
} from "../lib/userListings";
import { ListingForm } from "./ListingForm";
import "./MyListingsScreen.css";

interface Props {
  listings: MyListings;
  /**
   * 지금 문맥의 단지. 있으면 입력 폼이 열린다.
   * 없으면 **폼을 열지 않는다** — 단지를 모르는 호가는 어디에도 쓸 수 없고,
   * 단지 검색을 여기서 새로 만들면 지도와 다른 검색이 하나 더 생긴다.
   */
  complex: { id: number; name: string } | null;
  /** 단지 문맥을 풀고 전체 목록을 본다. */
  onClearComplex?: () => void;
  onClose: () => void;
}

/** 없는 값은 적지 않는다 — 빈칸으로 두면 "0층"·"면적 없음"으로 읽힌다. */
function metaText(item: UserListing): string {
  const parts = [`${item.area_m2}㎡`];
  parts.push(item.floor === null || item.floor === undefined ? "층 미상" : `${item.floor}층`);
  if (item.apt_dong) parts.push(item.apt_dong);
  return parts.join(" · ");
}

export function MyListingsScreen({ listings, complex, onClearComplex, onClose }: Props) {
  const { items, summary, notes, loading, error } = listings;

  const [editing, setEditing] = useState<UserListing | null>(null);
  const [busy, setBusy] = useState(false);
  /** 마지막 저장 결과 — **성공이어도 problems 가 있을 수 있다.** */
  const [saved, setSaved] = useState<SaveOutcome | null>(null);
  /** 삭제 확인 중인 항목. 되돌릴 수 없는 조작이라 한 번 더 묻는다. */
  const [confirmingDelete, setConfirmingDelete] = useState<number | null>(null);
  /**
   * 등록에 성공하면 폼을 비운다(이 값을 `key` 로 준다 → React 가 새로 마운트한다).
   * 안 비우면 방금 넣은 **날짜와 가격이 그대로 남아** 다음 매물에 붙는다 —
   * 이 화면이 가장 경계하는 종류의 거짓말이다.
   */
  const [formKey, setFormKey] = useState(0);

  // 목록이 갈리면(단지 문맥 변경) 진행 중이던 수정·확인을 접는다.
  useEffect(() => {
    setEditing(null);
    setConfirmingDelete(null);
  }, [complex?.id]);

  const fieldErrors: ListingErrors = serverFieldErrors(saved?.fields, saved?.problems);

  /**
   * 화면에 낼 고정 고지 = 목록 응답 + 저장 응답, **중복 제거**.
   * 저장 응답에만 실려 오는 문장이 있어도 사라지지 않고, 같은 문장이 두 번 뜨지도 않는다.
   */
  const notices = Array.from(new Set([...notes, ...(saved?.notes ?? [])]));

  const runSave = useCallback(async (fn: () => Promise<SaveOutcome>) => {
    setBusy(true);
    const outcome = await fn();
    setBusy(false);
    setSaved(outcome);
    return outcome;
  }, []);

  const submitForm = useCallback(
    async (values: ListingFormValues) => {
      if (editing) {
        const patch = buildPatch(editing, values);
        if ("error" in patch) {
          // 서버에 보내기 전에 화면이 먼저 말한다(가격↔날짜 규칙). 422 를 일부러 받지 않는다.
          setSaved({ ok: false, problems: [], notes: [], error: patch.error });
          return;
        }
        const out = await runSave(() => listings.update(editing.id, patch.body));
        if (out.ok) setEditing(null);
        return;
      }
      if (!complex) return;
      const out = await runSave(() => listings.create(buildCreate(complex.id, values)));
      if (out.ok) setFormKey((k) => k + 1); // 다음 매물에 옛 가격·날짜가 붙지 않게
    },
    [complex, editing, listings, runSave],
  );

  const changeStatus = useCallback(
    async (item: UserListing, status: "active" | "traded" | "withdrawn") => {
      if (status === item.status) return;
      await runSave(() => listings.update(item.id, statusPatch(status)));
    },
    [listings, runSave],
  );

  const doDelete = useCallback(
    async (id: number) => {
      setConfirmingDelete(null);
      await runSave(() => listings.remove(id));
    },
    [listings, runSave],
  );

  return (
    <div className="mlist">
      <button type="button" className="mlist__back" onClick={onClose}>
        ← 목록으로
      </button>

      <h3 className="mlist__title">내 매물 (직접 입력한 호가)</h3>

      {/* 서버 고지 — **원문 그대로**.
          ① 이 데이터가 공공 데이터가 아니라는 사실
          ② "반영 가능"이 "반영됐다"가 아니라는 사실(CR35-7 — 서버가 조건 없이 항상 보낸다)
          목록 응답과 저장 응답 둘 다에서 모은다. 같은 문장은 한 번만 — 저장 직후에는
          목록에도 같은 고지가 실려 오므로 그대로 두면 화면에 두 번 뜬다. */}
      {notices.length > 0 && (
        <ul className="mlist__notes">
          {notices.map((n, i) => (
            <li key={`${n}-${i}`}>{n}</li>
          ))}
        </ul>
      )}

      {summary && (
        <p className="mlist__summary" role="status">
          {complex ? `${complex.name} · ` : ""}
          {summaryText(summary)}
        </p>
      )}

      {complex && onClearComplex && (
        <button type="button" className="mlist__scope" onClick={onClearComplex}>
          전체 매물 보기
        </button>
      )}

      {error && (
        <p className="mlist__error" role="alert">
          {error}
        </p>
      )}

      {/* ── 저장 결과 ─────────────────────────────────────────────────────
          실패는 사유를, **성공은 problems 를** 말한다. 둘 다 조용히 넘기지 않는다. */}
      {saved && !saved.ok && saved.error && (
        <p className="mlist__error" role="alert">
          {saved.error}
        </p>
      )}
      {saved && saved.problems.length > 0 && (
        <section className="mlist__problems" role="status" aria-label="확인해 주세요">
          <p className="mlist__problems-head">
            {saved.ok ? "저장했습니다 — 다만 확인해 주세요" : "확인해 주세요"}
          </p>
          <ul className="mlist__problems-list">
            {saved.problems.map((p, i) => (
              <li key={`${p}-${i}`}>{p}</li>
            ))}
          </ul>
        </section>
      )}

      {/* ── 입력 ─────────────────────────────────────────────────────────
          단지 문맥이 있어야 연다. 단지 없는 호가는 어디에도 붙일 수 없다. */}
      {complex || editing ? (
        <ListingForm
          // 등록 성공 때마다 바뀐다 → 폼이 새로 마운트되며 값이 비워진다
          key={editing ? `edit-${editing.id}` : `new-${formKey}`}
          complexName={editing?.complex_name ?? complex?.name ?? "단지 미상"}
          editing={editing}
          busy={busy}
          serverFieldErrors={fieldErrors}
          onSubmit={submitForm}
          onCancel={editing ? () => setEditing(null) : undefined}
        />
      ) : (
        <p className="mlist__hint">
          호가를 넣으려면 먼저 단지를 고르세요 — 지도나 AI 추천에서 단지를 누른 뒤
          <strong> ‘호가 입력’</strong>을 누르면 이 화면이 그 단지로 열립니다.
        </p>
      )}

      {loading && items.length === 0 && <p className="mlist__loading">불러오는 중…</p>}

      {!loading && items.length === 0 && (
        <p className="mlist__empty">
          아직 입력한 호가가 없습니다. 호가가 없으면 <strong>가격 축(적정가 대비 싼가)</strong>이
          추천 점수에서 빠집니다 — 공공 데이터에는 호가가 없기 때문입니다.
        </p>
      )}

      <ul className="mlist__items">
        {items.map((item) => {
          const s = stalenessView(item);
          const label = sourceLabel(item);
          return (
            <li
              key={item.id}
              className={`mlist__item${s.eligible === true ? "" : " mlist__item--out"}`}
            >
              {/* 금액 — **공공 데이터와 다른 모양**이다(점선 테두리 · 약한 농도 · 출처 배지).
                  같은 모양으로 그리면 내가 손으로 친 숫자가 실거래가처럼 보인다. */}
              <p className="mlist__price num">
                {formatKrw(item.ask_price_krw)}
                {label ? (
                  // 서버가 준 문자열 그대로. 프론트가 라벨을 만들지 않는다.
                  <span className="badge mlist__source">{label}</span>
                ) : (
                  <span className="badge mlist__source mlist__source--unknown">출처 미상</span>
                )}
              </p>

              {item.complex_name && !complex && (
                <p className="mlist__complex">{item.complex_name}</p>
              )}

              <p className="mlist__meta">
                {metaText(item)}
                <span className="mlist__ppm">
                  {" · ㎡당 "}
                  {formatKrw(item.price_per_m2_krw)}
                </span>
              </p>

              <p className="mlist__asof">
                {formatAsOf(item.as_of)} · {s.ageText}
              </p>

              {/* 반영 **자격**은 서버 판정을 그대로 말한다(stale 을 반영된 것처럼 쓰지 않는다).
                  그리고 자격이 있어도 "반영됐다"고 단정하지 않는다 — 실제 반영은 그 단지가
                  추천 요청의 조건·후보 상한을 통과해야 하고, 그건 이 화면이 모른다. */}
              <p className={`mlist__usage${s.eligible === true ? "" : " mlist__usage--out"}`}>
                <span className="badge mlist__usage-badge">{s.badgeText}</span>
                {s.usageText}
              </p>

              {item.note && <p className="mlist__note">{item.note}</p>}

              <div className="mlist__actions">
                <button
                  type="button"
                  className="mlist__act"
                  onClick={() => {
                    setSaved(null);
                    setEditing(item);
                  }}
                >
                  {s.needsRefresh ? "갱신하기" : "수정"}
                </button>

                {/* 삭제와 다른 길: 지우지 않고 추천에서만 뺀다(기록은 남는다). */}
                <label className="mlist__statuswrap">
                  {/* 보조기기용 이름에 id 를 쓰는 이유: 같은 단지·면적·가격의 매물이
                      여러 건 있을 수 있어 다른 값으로는 구분되지 않는다. 그리고 서버
                      `problems` 도 중복을 알릴 때 같은 번호로 부른다("…(#12)"). */}
                  <span className="sr-only">{`${item.id}번 매물 상태`}</span>
                  <select
                    className="mlist__status"
                    value={item.status}
                    disabled={busy}
                    onChange={(e) =>
                      void changeStatus(
                        item,
                        e.target.value as "active" | "traded" | "withdrawn",
                      )
                    }
                  >
                    <option value="active">{statusLabel("active")}</option>
                    <option value="traded">{statusLabel("traded")}</option>
                    <option value="withdrawn">{statusLabel("withdrawn")}</option>
                  </select>
                </label>

                {confirmingDelete === item.id ? (
                  <span className="mlist__confirm" role="alert">
                    <span className="mlist__confirm-text">
                      지우면 되돌릴 수 없습니다. 팔렸거나 내려간 매물이면 위에서
                      ‘거래됨·내림’으로 바꾸세요 — 기록은 남고 추천에서만 빠집니다.
                    </span>
                    <button
                      type="button"
                      className="mlist__act mlist__act--danger"
                      onClick={() => void doDelete(item.id)}
                    >
                      영구 삭제
                    </button>
                    <button
                      type="button"
                      className="mlist__act"
                      onClick={() => setConfirmingDelete(null)}
                    >
                      취소
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="mlist__act mlist__act--danger"
                    onClick={() => setConfirmingDelete(item.id)}
                  >
                    삭제
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
