/**
 * 관리자 — 가입 승인 목록/처리 훅.
 *
 * 관리자인지 어떻게 아는가 (중요)
 * -------------------------------
 * **클라이언트가 판단하지 않는다.** JWT 에 `admin`·`role` 클레임이 없고(api-spec §6.1),
 * `/me/profile` 에도 권한 필드가 없다. 유일하게 확실한 방법은 **서버에 물어보는 것**이다:
 * `GET /admin/users` 가 200 이면 관리자, **404 면 관리자가 아니다.**
 *
 * 왜 404 를 "권한 없음"으로 표시하지 않는가
 * ----------------------------------------
 * 서버는 관리자가 아닌 모든 접근에 **403 이 아니라 404** 를 준다 — 관리 기능의 **존재
 * 자체를 숨기려는 의도적 설계**다(api-spec §6.2). 여기서 "권한이 없습니다"를 띄우면
 * 서버가 숨긴 것을 화면이 도로 알려주는 꼴이다. 그래서 404 는 **"그런 기능 없음"** 으로
 * 조용히 끝내고, 진입점 자체를 만들지 않는다.
 *
 * 진입점은 **200 을 실제로 받은 경우에만** 켠다. 모르면 보여주지 않는다 —
 * "일단 메뉴를 띄우고 눌렀을 때 404" 는 이 설계를 정면으로 깨뜨린다.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api } from "../api/client";
import {
  adminActionErrorMessage,
  applyUserUpdate,
  pendingCount,
  sanitizeAdminUser,
  sanitizeAdminUsers,
  type AdminUserSummary,
  type StatusFilter,
} from "../lib/adminUsers";

/** probing = 아직 모름(아무것도 보여주지 않는다) · unavailable = 이 사용자에겐 없는 기능 */
export type AdminAvailability = "probing" | "unavailable" | "available";

export interface UseAdminUsers {
  availability: AdminAvailability;
  users: AdminUserSummary[];
  pending: number;
  activeAdmins: number | null;
  filter: StatusFilter;
  loading: boolean;
  /** 목록을 못 불러온 일시적 오류(권한 문제가 아니다). */
  error: string | null;
  /** 승인·거부 결과 안내(성공/실패 공용). */
  actionError: string | null;
  actionDone: string | null;
  busyUserId: number | null;
  /** 서버 응답에 자산 등 민감 필드가 섞여 있었는가(버렸지만 알린다). */
  droppedSensitive: boolean;
  setFilter: (filter: StatusFilter) => void;
  reload: () => Promise<void>;
  approve: (userId: number) => Promise<void>;
  reject: (userId: number, reason: string | null) => Promise<void>;
}

export function useAdminUsers(enabled: boolean): UseAdminUsers {
  const [availability, setAvailability] = useState<AdminAvailability>("probing");
  const [users, setUsers] = useState<AdminUserSummary[]>([]);
  const [activeAdmins, setActiveAdmins] = useState<number | null>(null);
  const [filter, setFilterState] = useState<StatusFilter>("pending");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionDone, setActionDone] = useState<string | null>(null);
  const [busyUserId, setBusyUserId] = useState<number | null>(null);
  const [droppedSensitive, setDroppedSensitive] = useState(false);

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async (next: StatusFilter) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.adminListUsers({
        status: next === "all" ? undefined : next,
        limit: 200,
      });
      if (!alive.current) return;
      const { users: clean, droppedSensitive: dropped } = sanitizeAdminUsers(res?.items);
      setUsers(clean);
      setDroppedSensitive(dropped);
      setActiveAdmins(typeof res?.active_admins === "number" ? res.active_admins : null);
      setAvailability("available"); // 200 을 받은 지금에야 관리자임이 확인된다
    } catch (err) {
      if (!alive.current) return;
      if (err instanceof ApiException && err.status === 404) {
        // 관리자가 아니거나 강등됨 — 서버가 존재를 숨겼으니 화면도 조용히 없앤다.
        setAvailability("unavailable");
        setUsers([]);
        setActiveAdmins(null);
        setError(null);
        return;
      }
      // 일시적 오류. 아직 한 번도 200 을 못 받았다면 진입점을 켜지 않는다(모르면 숨긴다).
      setAvailability((prev) => (prev === "available" ? prev : "unavailable"));
      setError(
        err instanceof ApiException
          ? err.error.message || "목록을 불러오지 못했습니다."
          : "네트워크 오류로 목록을 불러오지 못했습니다.",
      );
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void load(filter);
  }, [enabled, filter, load]);

  const setFilter = useCallback((next: StatusFilter) => {
    setActionError(null);
    setActionDone(null);
    setFilterState(next); // 위 effect 가 새 필터로 다시 불러온다
  }, []);

  const reload = useCallback(() => load(filter), [filter, load]);

  /** 승인·거부 공통. 서버가 돌려준 **변경된 사용자**를 목록에 그대로 반영한다. */
  const act = useCallback(
    async (userId: number, run: () => Promise<unknown>, doneText: string) => {
      setBusyUserId(userId);
      setActionError(null);
      setActionDone(null);
      try {
        const updated = sanitizeAdminUser(await run());
        if (!alive.current) return;
        if (updated) {
          setUsers((prev) => applyUserUpdate(prev, updated, filter));
          setActionDone(`${updated.email} · ${doneText}`);
        } else {
          // 응답 형태가 계약과 다르면 지어내지 않고 서버에 다시 묻는다.
          await load(filter);
        }
      } catch (err) {
        if (!alive.current) return;
        setActionError(adminActionErrorMessage(err));
        // 404 는 "대상 없음"일 수도, "내 권한이 사라짐"일 수도 있다 — 서버가 구분하지
        // 않으므로 목록을 다시 불러와 확인한다(권한이 사라졌으면 화면이 닫힌다).
        if (err instanceof ApiException && err.status === 404) await load(filter);
      } finally {
        if (alive.current) setBusyUserId(null);
      }
    },
    [filter, load],
  );

  const approve = useCallback(
    (userId: number) => act(userId, () => api.adminApproveUser(userId), "승인했습니다"),
    [act],
  );

  const reject = useCallback(
    (userId: number, reason: string | null) =>
      act(userId, () => api.adminRejectUser(userId, reason), "거부했습니다"),
    [act],
  );

  return {
    availability,
    users,
    pending: pendingCount(users),
    activeAdmins,
    filter,
    loading,
    error,
    actionError,
    actionDone,
    busyUserId,
    droppedSensitive,
    setFilter,
    reload,
    approve,
    reject,
  };
}
