"""Minimal PoC-grade auth: bcrypt password hashing + a signed-cookie session
(Starlette's SessionMiddleware, installed in app.main). No JWT, no server-side
session store, no password reset/MFA/SSO — see README's "out of scope" list.

bcrypt is used directly rather than passlib — passlib's bcrypt backend has
known compatibility breakage with bcrypt>=4.1, and plain hashpw/checkpw is
all a PoC user store needs.
"""
import bcrypt
from fastapi import Depends, HTTPException, Request
from loguru import logger
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, UserRole


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False  # malformed hash — fail closed, not a crash


# Computed once at import time so a login attempt for a nonexistent username still pays
# the same bcrypt cost as a real password check. Without this, "user not found" returns
# measurably faster than "wrong password" (which calls verify_password), letting an
# attacker enumerate valid usernames purely by timing the login response.
DUMMY_PASSWORD_HASH = hash_password("not-a-real-account-used-only-to-equalize-login-timing")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Resolve the session cookie to a live User row. 401s if there's no
    session, or the session references a user that no longer exists (e.g. a
    reseed happened since the cookie was issued)."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(401, "Not authenticated")
    user = db.query(User).get(user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(401, "Not authenticated")
    return user


def require_role(*allowed: UserRole):
    """Dependency factory: 403s unless the current user's role is in `allowed`.
    Composes with get_current_user, so an unauthenticated request still 401s
    rather than 403s. Denied attempts are themselves logged with the actor —
    a blocked write is "who did what" signal too."""
    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            logger.bind(actor=user.username, context={
                "role": user.role.value, "required": [r.value for r in allowed],
            }).warning("User '{username}' (role {role}) was denied an action requiring {required}.",
                      username=user.username, role=user.role.value,
                      required=[r.value for r in allowed])
            raise HTTPException(
                403, f"This action requires role: {' or '.join(r.value for r in allowed)}.")
        return user
    return _dep
