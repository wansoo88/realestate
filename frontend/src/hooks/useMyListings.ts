/**
 * 내 매물(호가 직접 입력) 데이터 훅.
 *
 * 컴포넌트에서 fetch 를 부르지 않기 위해 훅으로 뺀다(components.md §1 · RN 재사용).
 *
 * 이 훅이 반드시 지키는 것
 * ------------------------
 *  ① **`problems` 를 버리지 않는다.** 201/200 이어도 서버는 "저장은 했지만 알아야 할 것"을
 *     함께 준다(단가 이상·낡음·중복). 여기서 흘리면 검증의 절반이 사라진다.
 *  ② **목록은 서버가 준 그대로** 들고 있는다(정렬·필터·합치기 없음). 낡은 것도 보여준다 —
 *     이 화면은 고치라고 있는 화면이라 숨기면 갱신할 대상을 볼 수 없다.
 *  ③ 저장 결과를 낙관적으로 반영하지 않는다. 저장 뒤 **다시 조회**한다 —
 *     `eligible_for_recommendation` 같은 판정은 서버만 알고, 화면이 흉내 내면 어긋난다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiException,
  api,
  type UserListing,
  type UserListingCreate,
  type UserListingList,
  type UserListingPatch,
} from "../api/client";

export interface MyListingsState {
  items: UserListing[];
  summary: UserListingList["summary"] | null;
  /** 서버 고지(출처·낡음). **원문 그대로** 보여준다. */
  notes: string[];
  loading: boolean;
  error: string | null;
}

/** 저장 결과 — 성공이어도 `problems` 가 있을 수 있다. */
export interface SaveOutcome {
  ok: boolean;
  /** 방금 저장/수정된 항목 id(성공 시). */
  id?: number;
  /** 서버가 조용히 넘기지 않은 것들. 성공/실패 모두에서 비어 있지 않을 수 있다. */
  problems: string[];
  /**
   * 항상 참인 고정 고지(출처 · 반영 자격의 한계). **저장 직후에 반드시 보여준다** —
   * 사용자가 `eligible_for_recommendation: true` 를 처음 보는 자리가 여기라서,
   * 여기서 조건을 말하지 않으면 목록을 보기도 전에 "반영됐다"고 믿는다(CR35-7).
   */
  notes: string[];
  /** 실패 사유(422 `detail.message` · 404 · 409 등). 성공이면 null. */
  error: string | null;
  /** 실패가 특정 입력 때문이면 그 필드 이름(pydantic `loc`). */
  fields?: string[];
}

const EMPTY_SUMMARY: UserListingList["summary"] = {
  total: 0,
  fresh: 0,
  aging: 0,
  stale: 0,
  inactive: 0,
  eligible_for_recommendation: 0,
};

/**
 * 서버 오류 → 화면 문구. **지어내지 않는다** — 서버가 준 문장이 있으면 그걸 쓴다.
 *
 * 409 `LIMIT_REACHED`(사용자당 상한)도 여기를 지난다. 상한 값을 프론트에 복사해 두지
 * 않는 이유: 두 곳에 적으면 서버가 값을 바꾸는 날 화면만 옛 숫자를 말한다.
 * 서버 문장이 현재 건수와 무엇을 하면 되는지(삭제·수정)를 이미 담고 있다.
 */
function messageOf(e: unknown, fallback: string): string {
  if (e instanceof ApiException) {
    if (e.status === 404) {
      // 남의 것과 없는 것이 같은 404 다(IDOR 규약). "권한 없음"으로 번역하지 않는다.
      return e.error.message || "매물을 찾을 수 없습니다.";
    }
    return e.error.message || fallback;
  }
  return "네트워크 오류로 실패했습니다.";
}

function outcomeFromError(e: unknown, fallback: string): SaveOutcome {
  const fields = e instanceof ApiException ? e.error.fields : undefined;
  const problems = e instanceof ApiException ? (e.error.problems ?? []) : [];
  return {
    ok: false,
    // 422 검증 실패는 문제 목록이 곧 사유다 — 첫 줄만 남기고 버리지 않는다.
    problems: problems.length > 1 ? problems : [],
    notes: [],
    error: messageOf(e, fallback),
    fields,
  };
}

export function useMyListings(enabled: boolean, complexId?: number | null) {
  const [state, setState] = useState<MyListingsState>({
    items: [],
    summary: null,
    notes: [],
    loading: false,
    error: null,
  });

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reqId = useRef(0);

  const load = useCallback(async (cid?: number | null) => {
    const id = (reqId.current += 1);
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const res = await api.listMyListings(cid ?? null);
      if (!alive.current || id !== reqId.current) return;
      setState({
        items: res.items ?? [],
        summary: res.summary ?? EMPTY_SUMMARY,
        notes: res.notes ?? [],
        loading: false,
        error: null,
      });
    } catch (e) {
      if (!alive.current || id !== reqId.current) return;
      setState((s) => ({
        ...s,
        loading: false,
        error: messageOf(e, "내 매물을 불러오지 못했습니다."),
      }));
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load(complexId);
  }, [enabled, complexId, load]);

  const create = useCallback(
    async (body: UserListingCreate): Promise<SaveOutcome> => {
      try {
        const res = await api.createMyListing(body);
        await load(complexId);
        // ⚠️ problems·notes 는 성공 응답에도 실린다. 화면이 반드시 렌더한다.
        return {
          ok: true,
          id: res.item.id,
          problems: res.problems ?? [],
          notes: res.notes ?? [],
          error: null,
        };
      } catch (e) {
        return outcomeFromError(e, "호가를 저장하지 못했습니다.");
      }
    },
    [complexId, load],
  );

  const update = useCallback(
    async (id: number, patch: UserListingPatch): Promise<SaveOutcome> => {
      try {
        const res = await api.updateMyListing(id, patch);
        await load(complexId);
        return {
          ok: true,
          id: res.item.id,
          problems: res.problems ?? [],
          notes: res.notes ?? [],
          error: null,
        };
      } catch (e) {
        return outcomeFromError(e, "수정하지 못했습니다.");
      }
    },
    [complexId, load],
  );

  const remove = useCallback(
    async (id: number): Promise<SaveOutcome> => {
      try {
        await api.deleteMyListing(id);
        await load(complexId);
        return { ok: true, id, problems: [], notes: [], error: null };
      } catch (e) {
        return outcomeFromError(e, "삭제하지 못했습니다.");
      }
    },
    [complexId, load],
  );

  return { ...state, create, update, remove, reload: () => load(complexId) };
}

export type MyListings = ReturnType<typeof useMyListings>;
