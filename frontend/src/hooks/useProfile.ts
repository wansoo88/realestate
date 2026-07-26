/**
 * 내 조건(자산·선호) 로딩·저장.
 *
 * ⚠️ `status === "missing"` 은 **에러가 아니라 흐름**이다.
 * 자산이 없으면 예산도, 추천도, "내 조건에 맞는 매물"도 존재할 수 없다.
 * 그래서 화면은 이 상태에서 지도가 아니라 **조건 입력**으로 사용자를 보낸다.
 *
 * 🔐 여기서 다루는 값(현금·소득·대출)은 개인 금융정보다. 로깅·저장소 기록 금지.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiException, api, type Preferences, type Profile } from "../api/client";

export type ProfileStatus = "loading" | "missing" | "ready" | "error";

/** 서버가 선호를 저장한 적 없을 때의 기본형(빈 구조). 값을 지어내지 않는다. */
export const EMPTY_PREFERENCES: Preferences = { prefer: {}, avoid: {}, weights: {} };

export interface ProfileState {
  status: ProfileStatus;
  profile: Profile | null;
  preferences: Preferences;
  error: string | null;
}

export interface UseProfile extends ProfileState {
  reload: () => Promise<void>;
  save: (profile: Profile, preferences: Preferences) => Promise<void>;
}

function normalize(p: Preferences | null | undefined): Preferences {
  return {
    prefer: p?.prefer ?? {},
    avoid: p?.avoid ?? {},
    weights: p?.weights ?? {},
  };
}

export function useProfile(): UseProfile {
  const [state, setState] = useState<ProfileState>({
    status: "loading",
    profile: null,
    preferences: EMPTY_PREFERENCES,
    error: null,
  });

  // 언마운트 후 setState 를 막는다(로그아웃 직후 응답이 늦게 도착하는 경우).
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setState((s) => ({ ...s, status: "loading", error: null }));

    // 선호는 프로필이 없어도 조회된다(빈 구조 200). 둘을 따로 처리해야
    // "자산만 없는" 정상 상태를 에러로 뭉개지 않는다.
    const [profileRes, prefsRes] = await Promise.allSettled([
      api.getProfile(),
      api.getPreferences(),
    ]);
    if (!alive.current) return;

    const preferences =
      prefsRes.status === "fulfilled" ? normalize(prefsRes.value) : EMPTY_PREFERENCES;

    if (profileRes.status === "fulfilled") {
      setState({ status: "ready", profile: profileRes.value, preferences, error: null });
      return;
    }

    const err = profileRes.reason;
    if (err instanceof ApiException && err.status === 404) {
      setState({ status: "missing", profile: null, preferences, error: null });
      return;
    }
    setState({
      status: "error",
      profile: null,
      preferences,
      error:
        err instanceof ApiException
          ? err.error.message || "내 조건을 불러오지 못했습니다."
          : "네트워크 오류로 내 조건을 불러오지 못했습니다.",
    });
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const save = useCallback(async (profile: Profile, preferences: Preferences) => {
    // 자산 저장이 성공해야 선호를 저장한다 — 순서가 반대면 자산 없이 선호만 남는다.
    const savedProfile = await api.putProfile(profile);
    const savedPrefs = await api.putPreferences(preferences);
    if (!alive.current) return;
    setState({
      status: "ready",
      profile: savedProfile,
      preferences: normalize(savedPrefs),
      error: null,
    });
  }, []);

  return { ...state, reload, save };
}
