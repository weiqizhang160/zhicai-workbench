# -*- coding: utf-8 -*-
"""认证 API：登录 / 登出 / 当前用户 / 修改密码（项目书 7.1）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.errors import BizError
from ..core.security import (SESSION_COOKIE, create_session_token, hash_password,
                             verify_password)
from ..modules.base.models import ResUsers
from .deps import get_current_user, require_login

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginBody(BaseModel):
    login: str
    password: str


class PasswordBody(BaseModel):
    old_password: str
    new_password: str


def _user_payload(db: Session, user: ResUsers) -> dict:
    role_code, role_name = "viewer", "只读"
    if user.role_id:
        from ..modules.base.models import ResRole
        role = db.get(ResRole, user.role_id)
        if role:
            role_code, role_name = role.code, role.name
    return {"id": user.id, "login": user.login, "name": user.name,
            "role_code": role_code, "role_name": role_name}


@router.post("/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)):
    user = db.execute(
        select(ResUsers).where(ResUsers.login == body.login, ResUsers.active.is_(True))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise BizError("login_failed", "账号或密码错误")
    user.last_login_at = datetime.now()
    db.flush()
    token = create_session_token(user.id)
    response.set_cookie(
        SESSION_COOKIE, token, httponly=True, samesite="lax",
        max_age=12 * 3600, path="/",
    )
    return {"ok": True, "user": _user_payload(db, user)}


@router.post("/logout")
def logout(response: Response, _user: ResUsers = Depends(require_login)):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: ResUsers | None = Depends(get_current_user), db: Session = Depends(get_db)):
    if user is None:
        return {"user": None}
    return {"user": _user_payload(db, user)}


@router.put("/password")
def change_password(body: PasswordBody, user: ResUsers = Depends(require_login)):
    if not verify_password(body.old_password, user.password_hash):
        raise BizError("old_password_wrong", "原密码不正确")
    if len(body.new_password) < 6:
        raise BizError("password_too_short", "新密码至少 6 位")
    user.password_hash = hash_password(body.new_password)
    return {"ok": True}
