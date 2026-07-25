// @vitest-environment jsdom
/**
 * 로그인/회원가입 폼 테스트 (FE-1).
 * api.login/register 를 스파이로 대체해 폼 동작·검증·에러 표기를 검증한다(실제 서버 미접속).
 */
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiException, api, type TokenResponse } from "../api/client";
import { AuthForm } from "./AuthForm";

const TOKENS: TokenResponse = { access_token: "a", token_type: "bearer", expires_in: 1800 };

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("로그인", () => {
  it("이메일·비밀번호로 로그인하고 onSuccess 를 부른다", async () => {
    const onSuccess = vi.fn();
    // 새 계약: 응답 body 에 refresh_token 이 없다(HttpOnly 쿠키로만 내려온다).
    const loginSpy = vi.spyOn(api, "login").mockResolvedValue(TOKENS);
    const user = userEvent.setup();

    render(<AuthForm onSuccess={onSuccess} />);
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(loginSpy).toHaveBeenCalledWith("me@example.com", "password12345");
    expect(onSuccess).toHaveBeenCalled();
  });

  it("실패 시 계정 존재를 드러내지 않는 합친 에러를 보인다", async () => {
    vi.spyOn(api, "login").mockRejectedValue(
      new ApiException(401, { code: "UNAUTHORIZED", message: "no" }),
    );
    const user = userEvent.setup();

    render(<AuthForm />);
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    await user.click(screen.getByRole("button", { name: "로그인" }));

    expect(await screen.findByText(/올바르지 않습니다/)).toBeTruthy();
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

describe("회원가입", () => {
  it("규칙을 미리 보이고, 짧은 비밀번호는 제출을 막고, 유효하면 가입→자동 로그인", async () => {
    const user = userEvent.setup();
    render(<AuthForm />);

    await user.click(screen.getByRole("button", { name: /회원가입/ }));
    expect(screen.getByText("12자 이상")).toBeTruthy();

    const submit = screen.getByRole("button", { name: "가입하고 시작" }) as HTMLButtonElement;
    await user.type(screen.getByLabelText("이메일"), "me@example.com");
    await user.type(screen.getByLabelText("비밀번호"), "short");
    expect(submit.disabled).toBe(true);

    await user.clear(screen.getByLabelText("비밀번호"));
    await user.type(screen.getByLabelText("비밀번호"), "password12345");
    expect(submit.disabled).toBe(false);

    const reg = vi.spyOn(api, "register").mockResolvedValue({ user_id: 1 });
    const log = vi.spyOn(api, "login").mockResolvedValue(TOKENS);

    await user.click(submit);
    expect(reg).toHaveBeenCalledWith("me@example.com", "password12345");
    expect(log).toHaveBeenCalled();
  });
});
