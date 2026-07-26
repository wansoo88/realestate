/**
 * 로그인 · 회원가입 (FE-1 · 관리자 승인제 ADM-1)
 *
 * 컨셉 "확신의 농도" + 애플 톤: iOS 설정앱식 inset grouped list.
 * 필드마다 박스를 두르지 않고 하나의 카드에 모아 헤어라인으로만 구분한다.
 * 라지 타이틀(좌측 정렬) · 폭 100% 파란 CTA(하단, 엄지 범위) · 보조 동작은 텍스트 버튼.
 * 에러는 필드 아래 작은 빨강 텍스트(모달·alert 금지, ux components.md §5.1).
 *
 * 승인제가 바꾼 두 가지
 * ---------------------
 * 1. **가입 → 자동 로그인을 하지 않는다.** 계정은 `pending` 으로 만들어져 로그인이 막혀 있다.
 *    이어 붙이면 "가입 성공 직후 실패" 라는 최악의 첫인상이 된다. 대신 접수 안내를 띄우고
 *    로그인 모드로 자연스럽게 돌려보낸다.
 * 2. **403 은 오류가 아니라 상태**다(승인 대기/거부). 빨간 에러가 아니라 안내 배너로 보인다.
 *    반면 **401 은 문구가 갈라지지 않는다** — 이유는 lib/authMessages.ts 참고.
 *
 * 검증 규칙은 lib/validation.ts(순수 함수, 서버 계약 복사)를 재사용한다 — 뷰에서 규칙을 새로 만들지 않는다.
 */
import { useState } from "react";
import { api, clearAuthNotice, getAuthNotice } from "../api/client";
import {
  bannerFromNotice,
  loginFeedback,
  registerErrorMessage,
  registerSubmittedBanner,
  type AuthBanner,
} from "../lib/authMessages";
import { NOTICE_TRUST } from "../lib/notices";
import { canSubmitPassword, isEmailShaped, passwordRules } from "../lib/validation";
import "./AuthForm.css";

type Mode = "login" | "signup";

interface Props {
  onSuccess?: () => void;
}

export function AuthForm({ onSuccess }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 세션 도중 승인이 회수돼 여기로 튕겨 온 경우, client 가 남긴 사유를 그대로 이어받는다.
  // 읽기만 하는 순수 조회다(StrictMode 이중 호출에도 같은 값) — 비우는 건 제출 시점이다.
  const [banner, setBanner] = useState<AuthBanner | null>(() =>
    bannerFromNotice(getAuthNotice()),
  );
  const [busy, setBusy] = useState(false);

  const rules = passwordRules(password);
  const emailOk = isEmailShaped(email);
  const pwOk = mode === "login" ? password.length > 0 : canSubmitPassword(password);
  const canSubmit = emailOk && pwOk && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setBanner(null);
    clearAuthNotice(); // 새로 시도하는 순간 지난 안내는 끝난다(폼이 다시 마운트돼도 안 뜬다)

    if (mode === "signup") {
      try {
        const res = await api.register(email.trim(), password);
        // ⚠️ 여기에 api.login 을 이어 붙이지 마라(계정은 아직 pending 이다).
        setBanner(registerSubmittedBanner(res?.message));
        setMode("login");
        setPassword(""); // 승인 전까지는 쓸 수 없다 — 폼에 남겨둘 이유가 없다
      } catch (err) {
        setError(registerErrorMessage(err));
      } finally {
        setBusy(false);
      }
      return;
    }

    try {
      await api.login(email.trim(), password);
      onSuccess?.();
      // 성공 시엔 상위(App)가 지도로 전환하므로 busy 를 되돌릴 필요가 없다.
    } catch (err) {
      const feedback = loginFeedback(err);
      if (feedback.kind === "banner") {
        setBanner(feedback.banner); // 승인 대기/거부 — 사용자 잘못이 아니다
        setPassword("");
      } else {
        setError(feedback.message);
      }
      setBusy(false);
    }
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setBanner(null);
  }

  const isSignup = mode === "signup";

  return (
    <main className="auth">
      <form className="auth__form" onSubmit={submit} noValidate>
        <header className="auth__header">
          <h1 className="auth__title">부동산 AI 자문</h1>
          <p className="auth__lede">
            {isSignup
              ? "가입 신청 후 관리자 승인을 받으면 이용할 수 있습니다."
              : "다시 오셨네요. 로그인하세요."}
          </p>
        </header>

        {/* 상태 안내(승인 대기·거부·가입 접수)는 에러가 아니다 — 빨강이 아니라 조용한 카드.
            role="status" 로 스크린리더에도 전달한다(모달 금지). */}
        {banner && (
          <section
            className={`auth__banner auth__banner--${banner.tone}`}
            role="status"
            aria-live="polite"
          >
            <h2 className="auth__banner-title">{banner.title}</h2>
            <p className="auth__banner-body">{banner.body}</p>
          </section>
        )}

        {/* inset grouped list — 카드 하나에 필드를 모으고 헤어라인으로만 구분 */}
        <div className="auth__group">
          <div className="auth__row">
            <label className="auth__label" htmlFor="auth-email">
              이메일
            </label>
            <input
              id="auth-email"
              className="auth__input"
              type="email"
              inputMode="email"
              enterKeyHint="next"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              aria-invalid={email.length > 0 && !emailOk}
              required
            />
          </div>

          <div className="auth__row">
            <label className="auth__label" htmlFor="auth-password">
              비밀번호
            </label>
            <div className="auth__pw">
              <input
                id="auth-password"
                className="auth__input"
                type={showPw ? "text" : "password"}
                enterKeyHint={isSignup ? "next" : "go"}
                autoComplete={isSignup ? "new-password" : "current-password"}
                placeholder={isSignup ? "12자 이상" : "비밀번호"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-invalid={isSignup && password.length > 0 && !pwOk}
                required
              />
              <button
                type="button"
                className="auth__pw-toggle"
                aria-pressed={showPw}
                aria-label={showPw ? "비밀번호 숨기기" : "비밀번호 표시"}
                onClick={() => setShowPw((s) => !s)}
              >
                {showPw ? "숨김" : "표시"}
              </button>
            </div>
          </div>
        </div>

        {/* 가입 시에만 비밀번호 규칙을 입력 전부터 노출(색만이 아니라 텍스트로) */}
        {isSignup && (
          <ul className="auth__rules" aria-label="비밀번호 조건">
            {rules.map((r) => (
              <li
                key={r.id}
                className={`auth__rule${r.ok ? " auth__rule--ok" : ""}`}
              >
                <span className="auth__rule-mark" aria-hidden="true">
                  {r.ok ? "✓" : "○"}
                </span>
                <span>{r.label}</span>
                {r.ok && <span className="sr-only"> 충족됨</span>}
              </li>
            ))}
          </ul>
        )}

        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}

        <div className="auth__actions">
          <button type="submit" className="auth__submit" disabled={!canSubmit}>
            {busy ? "처리 중…" : isSignup ? "가입 신청" : "로그인"}
          </button>

          <button
            type="button"
            className="auth__switch"
            onClick={() => switchMode(isSignup ? "login" : "signup")}
          >
            {isSignup ? "이미 계정이 있어요 · 로그인" : "계정이 없어요 · 가입 신청"}
          </button>

          {/* 민감정보 입력 전에 신뢰 문구를 미리 보인다(lib/notices, 규칙 5: 조용하지만 상시) */}
          <p className="auth__trust">{NOTICE_TRUST}</p>
        </div>
      </form>
    </main>
  );
}
