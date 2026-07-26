// @vitest-environment jsdom
/**
 * 로그인/회원가입 폼 테스트 (FE-1 · 승인제 ADM-1).
 * api.login/register 를 스파이로 대체해 폼 동작·검증·에러 표기를 검증한다(실제 서버 미접속).
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiException, api, setAuthNotice, type TokenResponse } from "../api/client";
import { AuthForm } from "./AuthForm";

const TOKENS: TokenResponse = { access_token: "a", token_type: "bearer", expires_in: 1800 };

afterEach(() => {
  cleanup();
  setAuthNotice(null); // 테스트 간에 안내가 새지 않게
  vi.restoreAllMocks();
});

async function fillAndLogin(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("이메일"), "me@example.com");
  await user.type(screen.getByLabelText("비밀번호"), "password12345");
  await user.click(screen.getByRole("button", { name: "로그인" }));
}

describe("로그인", () => {
  it("이메일·비밀번호로 로그인하고 onSuccess 를 부른다", async () => {
    const onSuccess = vi.fn();
    // 새 계약: 응답 body 에 refresh_token 이 없다(HttpOnly 쿠키로만 내려온다).
    const loginSpy = vi.spyOn(api, "login").mockResolvedValue(TOKENS);
    const user = userEvent.setup();

    render(<AuthForm onSuccess={onSuccess} />);
    await fillAndLogin(user);

    expect(loginSpy).toHaveBeenCalledWith("me@example.com", "password12345");
    expect(onSuccess).toHaveBeenCalled();
  });

  it("실패 시 계정 존재를 드러내지 않는 합친 에러를 보인다", async () => {
    vi.spyOn(api, "login").mockRejectedValue(
      new ApiException(401, { code: "UNAUTHORIZED", message: "no" }),
    );
    const user = userEvent.setup();

    render(<AuthForm />);
    await fillAndLogin(user);

    expect(await screen.findByText(/올바르지 않습니다/)).toBeTruthy();
  });

  /**
   * 계정 열거 방지 — **화면까지** 지켜지는지 본다.
   * 서버가 실수로 401 에 서로 다른 사유를 실어도, 사용자가 보는 글자는 똑같아야 한다.
   */
  it("401 문구는 서버가 뭐라 하든 상태별로 갈리지 않는다", async () => {
    const payloads = [
      { code: "UNAUTHORIZED", message: "이메일 또는 비밀번호가 올바르지 않습니다" },
      { code: "USER_NOT_FOUND", message: "가입되지 않은 이메일입니다" },
      { code: "PENDING_APPROVAL", message: "승인 대기 중입니다" },
    ];
    const seen: string[] = [];

    for (const payload of payloads) {
      vi.spyOn(api, "login").mockRejectedValue(new ApiException(401, payload));
      const user = userEvent.setup();
      render(<AuthForm />);
      await fillAndLogin(user);

      seen.push((await screen.findByRole("alert")).textContent ?? "");
      // 401 은 "상태"가 아니다 — 승인 안내(배너)로 승격되면 안 된다
      expect(screen.queryByRole("status")).toBeNull();

      cleanup();
      vi.restoreAllMocks();
    }

    expect(new Set(seen).size).toBe(1);
    expect(seen[0]).not.toContain("가입되지 않은");
    expect(seen[0]).not.toContain("승인");
  });

  it("403 PENDING_APPROVAL 은 오류가 아니라 승인 대기 안내로 보인다", async () => {
    vi.spyOn(api, "login").mockRejectedValue(
      new ApiException(403, {
        code: "PENDING_APPROVAL",
        message: "관리자 승인 대기 중입니다. 승인되면 로그인할 수 있습니다.",
      }),
    );
    const user = userEvent.setup();

    render(<AuthForm />);
    await fillAndLogin(user);

    const banner = await screen.findByRole("status");
    expect(banner.textContent).toContain("승인 대기 중입니다");
    expect(banner.textContent).toContain("관리자가 승인하면");
    // 빨간 에러가 아니라 안내다
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("403 ACCOUNT_REJECTED 는 거부 안내로 보인다", async () => {
    vi.spyOn(api, "login").mockRejectedValue(
      new ApiException(403, { code: "ACCOUNT_REJECTED", message: "승인되지 않았습니다" }),
    );
    const user = userEvent.setup();

    render(<AuthForm />);
    await fillAndLogin(user);

    expect((await screen.findByRole("status")).textContent).toContain("가입이 거부되었습니다");
  });

  it("세션 도중 승인이 회수돼 튕겨 오면 그 사유를 이어서 보여준다", async () => {
    // client 가 403 을 만나 남겨 둔 안내를 로그인 화면이 이어받는다.
    setAuthNotice({ code: "PENDING_APPROVAL", message: "승인 대기", reason: null });

    // ⚠️ StrictMode 로 감싼 건 의도다: useState 초기화 함수가 두 번 불린다.
    // "읽으면 비운다"로 만들면 여기서 안내가 사라진다(개발 모드에서만 나는 버그).
    render(
      <StrictMode>
        <AuthForm />
      </StrictMode>,
    );

    expect(screen.getByRole("status").textContent).toContain("승인 대기 중입니다");
  });

  it("비밀번호 표시 토글이 input type 을 바꾼다", async () => {
    const user = userEvent.setup();
    render(<AuthForm />);
    const pw = screen.getByLabelText("비밀번호") as HTMLInputElement;

    expect(pw.type).toBe("password");
    await user.click(screen.getByRole("button", { name: "비밀번호 표시" }));
    expect(pw.type).toBe("text");
  });
});

describe("회원가입 (승인제)", () => {
  it("규칙을 미리 보이고, 짧은 비밀번호는 제출을 막는다", async () => {
    const user = userEvent.setup();
    render(<AuthForm />);

    await user.click(screen.getByRole("button", { name: /가입 신청/ }));
    expect(screen.getByText("12자 이상")).toBeTruthy();

    const submit = screen.getByRole("button", { name: "가입 신청" }) as HTMLButtonElement;
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "short");
    expect(submit.disabled).toBe(true);

    await user.clear(screen.getByLabelText("비밀번호"));
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    expect(submit.disabled).toBe(false);
  });

  it("가입은 **접수**로 끝난다 — 자동 로그인하지 않고 승인 안내를 보인다", async () => {
    const reg = vi.spyOn(api, "register").mockResolvedValue({
      user_id: 1,
      status: "pending",
      message: "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
    });
    const log = vi.spyOn(api, "login").mockResolvedValue(TOKENS);

    const user = userEvent.setup();
    render(<AuthForm />);
    await user.click(screen.getByRole("button", { name: /가입 신청/ }));
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    await user.click(screen.getByRole("button", { name: "가입 신청" }));

    expect(reg).toHaveBeenCalledWith("me@example.com", "password12345");
    // ⚠️ 계정이 pending 이라 곧바로 403 이 된다 — 자동 로그인을 붙이면 안 된다
    expect(log).not.toHaveBeenCalled();

    const banner = await screen.findByRole("status");
    expect(banner.textContent).toContain("접수");
    expect(banner.textContent).toContain("관리자 승인");
    // 로그인 화면으로 자연스럽게 되돌아온다
    expect(screen.getByRole("button", { name: "로그인" })).toBeTruthy();
  });

  it("이미 신청된 이메일은 다시 신청하지 않도록 알려준다", async () => {
    vi.spyOn(api, "register").mockRejectedValue(
      new ApiException(409, { code: "EMAIL_TAKEN", message: "이미 가입된 이메일" }),
    );

    const user = userEvent.setup();
    render(<AuthForm />);
    await user.click(screen.getByRole("button", { name: /가입 신청/ }));
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    await user.click(screen.getByRole("button", { name: "가입 신청" }));

    expect((await screen.findByRole("alert")).textContent).toContain("이미");
  });
});
