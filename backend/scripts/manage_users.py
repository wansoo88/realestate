"""가입 승인 운영 CLI — 첫 관리자를 만들고, 대기 계정을 승인·거부한다.

왜 API 가 아니라 CLI 인가 (부트스트랩 문제)
-------------------------------------------
승인제를 켜면 닭과 달걀 문제가 남는다: **승인할 관리자가 아직 없다.**
흔한 해법인 "첫 가입자를 자동으로 관리자"는 이 프로젝트에서 쓸 수 없다 —
사이트가 이미 공개돼 있어(https://realestate.utilverse.info) 남이 먼저 가입하면
그 사람이 관리자가 된다. 지금 nginx 로 가입을 막아 둔 상태라 해도, 그 임시 조치가
풀리는 순간이 정확히 이 스크립트가 대체하려는 창(窓)이다.

그래서 관리자 부여는 **서버에 SSH 로 들어와야만** 되는 이 스크립트로만 한다.
인터넷에서 도달할 수 있는 경로가 없으므로 선점당할 표면이 없다.

⚠️ 이 스크립트는 **비밀번호를 다루지 않는다.**
   비밀번호는 사용자가 가입할 때 스스로 정한다. 운영자가 하는 일은 **승인**뿐이다.
   (계정을 만들어 주는 기능도 일부러 없다 — 그러면 운영자가 남의 비밀번호를 알게 된다.)

사용
----
    # 서버에서
    cd /opt/realestate/backend
    python scripts/manage_users.py --list                    # 누가 기다리는지 본다
    python scripts/manage_users.py --approve me@example.com  # 승인
    python scripts/manage_users.py --grant-admin me@example.com   # 관리자 부여
    python scripts/manage_users.py --history me@example.com  # 감사 이력

    # 되돌리기
    python scripts/manage_users.py --reject someone@example.com --reason "본인 확인 불가"
    python scripts/manage_users.py --revoke-admin someone@example.com

첫 관리자 만들기 (부트스트랩 순서)
----------------------------------
    1. 본인이 웹에서 가입한다 (계정은 pending 으로 만들어진다)
    2. --list 로 그 이메일이 맞는지 **눈으로 확인**한다
    3. --approve <email>  →  4. --grant-admin <email>
    이후로는 웹의 관리자 화면(`GET /api/v1/admin/users`)에서 처리할 수 있다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# ⚠️ `_common` import 자체가 로깅 억제·마스킹을 설치한다(SR17-3). 지우지 말 것.
from _common import load_env, make_engine  # noqa: E402

from app.repositories.base import (  # noqa: E402
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    LastAdminError,
)
from app.repositories.postgis import PostgisRepository  # noqa: E402

#: CLI 로 한 변경은 감사 이력에 이 actor 로 남는다(관리자 API 와 구분된다).
ACTOR = "cli"

_STATUS_LABEL = {STATUS_PENDING: "대기", STATUS_APPROVED: "승인", STATUS_REJECTED: "거부"}


def _fmt(user) -> str:
    when = user.created_at.strftime("%Y-%m-%d %H:%M") if user.created_at else "-"
    flag = " [관리자]" if user.is_admin else ""
    reason = f" · 사유: {user.status_reason}" if user.status_reason else ""
    return (f"  #{user.id:<5} {user.email:<32} {_STATUS_LABEL.get(user.status, user.status)}"
            f"{flag}  가입 {when}{reason}")


def cmd_list(repo, status: str | None, limit: int) -> int:
    users = repo.list_users(status=status, limit=limit)
    label = _STATUS_LABEL.get(status, "전체") if status else "전체"
    print(f"[사용자 {label}] {len(users)}건 (승인된 관리자 {repo.count_active_admins()}명)")
    if not users:
        print("  (없음)")
    for u in users:
        print(_fmt(u))
    return 0


def _find(repo, email: str):
    """이메일로 찾는다. 없으면 **조용히 성공하지 않는다** — 오타를 승인으로 착각하면 안 된다."""
    user = repo.get_user_by_email(email)
    if user is None:
        print(f"[FAIL] 그런 계정이 없습니다: {email}\n"
              f"       --list 로 정확한 주소를 확인하세요(대소문자는 무시됩니다).")
    return user


def cmd_status(repo, email: str, new_status: str, reason: str | None) -> int:
    user = _find(repo, email)
    if user is None:
        return 1
    if user.status == new_status:
        print(f"[SKIP] 이미 {_STATUS_LABEL[new_status]} 상태입니다: {email}")
        return 0
    try:
        updated = repo.set_user_status(user.id, new_status, actor=ACTOR, reason=reason)
    except LastAdminError as exc:
        print(f"[FAIL] {exc}\n"
              f"       --grant-admin 으로 다른 관리자를 먼저 지정하세요.")
        return 1
    print(f"[OK] {updated.email} → {_STATUS_LABEL[new_status]}"
          + (f" (사유: {reason})" if reason else ""))
    if new_status == STATUS_APPROVED and not updated.is_admin:
        print("     관리자로도 쓰려면: --grant-admin " + updated.email)
    return 0


def cmd_admin(repo, email: str, grant: bool) -> int:
    user = _find(repo, email)
    if user is None:
        return 1
    if grant and user.status != STATUS_APPROVED:
        # 승인되지 않은 관리자는 관리자가 아니다(UserRecord.can_administer).
        # 여기서 자동 승인해 버리면 "관리자 부여"가 승인 절차를 건너뛰는 뒷문이 된다.
        print(f"[FAIL] 아직 승인되지 않은 계정입니다({_STATUS_LABEL.get(user.status)}). "
              f"먼저 실행하세요:\n       --approve {user.email}")
        return 1
    if user.is_admin == grant:
        print(f"[SKIP] 이미 {'관리자' if grant else '일반 사용자'}입니다: {user.email}")
        return 0
    try:
        updated = repo.set_user_admin(user.id, grant, actor=ACTOR)
    except LastAdminError as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[OK] {updated.email} → {'관리자 부여' if grant else '관리자 해제'} "
          f"(승인된 관리자 {repo.count_active_admins()}명)")
    return 0


def cmd_history(repo, email: str) -> int:
    user = _find(repo, email)
    if user is None:
        return 1
    events = repo.status_events(user.id)
    print(f"[이력] {user.email} — {len(events)}건")
    for e in events:
        when = e["created_at"].strftime("%Y-%m-%d %H:%M:%S") if e["created_at"] else "-"
        actor = e["actor"] + (f"(#{e['actor_user_id']})" if e["actor_user_id"] else "")
        print(f"  {when}  {e['event']:<14} by {actor}"
              + (f" · {e['reason']}" if e.get("reason") else ""))
    return 0


def run(repo, args: argparse.Namespace) -> int:
    """명령 분기. **리포지토리를 인자로 받는다** — 테스트가 인메모리 구현으로 돌린다."""
    if args.list is not None:
        return cmd_list(repo, args.list or None, args.limit)
    if args.approve:
        return cmd_status(repo, args.approve, STATUS_APPROVED, None)
    if args.reject:
        return cmd_status(repo, args.reject, STATUS_REJECTED, args.reason)
    if args.grant_admin:
        return cmd_admin(repo, args.grant_admin, True)
    if args.revoke_admin:
        return cmd_admin(repo, args.revoke_admin, False)
    if args.history:
        return cmd_history(repo, args.history)
    print("할 일을 하나 고르세요. --help 를 보세요.")
    return 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="가입 승인 운영 CLI (서버에서 실행 · 비밀번호는 다루지 않는다)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", nargs="?", const="", metavar="STATUS",
                   choices=["", STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED],
                   help="사용자 목록(기본 전체). 예: --list pending")
    g.add_argument("--approve", metavar="EMAIL", help="가입 승인")
    g.add_argument("--reject", metavar="EMAIL", help="가입 거부(승인 회수에도 쓴다)")
    g.add_argument("--grant-admin", metavar="EMAIL", help="관리자 부여(승인된 계정만)")
    g.add_argument("--revoke-admin", metavar="EMAIL", help="관리자 해제")
    g.add_argument("--history", metavar="EMAIL", help="상태 변경 이력")
    ap.add_argument("--reason", default=None, help="--reject 사유(감사 기록에 남는다)")
    ap.add_argument("--limit", type=int, default=200, help="--list 최대 건수")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env()
    engine = make_engine()
    repo = PostgisRepository(engine)
    try:
        return run(repo, args)
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
