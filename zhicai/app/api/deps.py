# -*- coding: utf-8 -*-
"""API 依赖注入：当前用户 / 角色守卫 / 当前账套。"""
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.db import get_db
from ..core.errors import BizError
from ..core.security import parse_session_token, role_can, SESSION_COOKIE
from ..modules.base.models import ResRole, ResUsers


def get_current_user(request: Request, db: Session = Depends(get_db)) -> ResUsers | None:
    """从会话 cookie 解析当前用户（未登录返回 None）。"""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = parse_session_token(token)
    if uid is None:
        return None
    user = db.get(ResUsers, uid)
    if user is None or not user.active:
        return None
    return user


def require_login(user: ResUsers | None = Depends(get_current_user)) -> ResUsers:
    if user is None:
        raise BizError("unauthorized", "登录已过期，请重新登录")
    return user


def user_role_code(db: Session, user: ResUsers) -> str:
    """取用户角色代码（无角色按 viewer 只读处理）。"""
    if not user.role_id:
        return "viewer"
    role = db.get(ResRole, user.role_id)
    return role.code if role else "viewer"


def require_role(action: str):
    """角色权限守卫工厂：action ∈ read/create/write/delete。

    admin 全权；accountant 读写无删除；viewer 只读。
    """
    def guard(user: ResUsers = Depends(require_login),
              db: Session = Depends(get_db)) -> ResUsers:
        code = user_role_code(db, user)
        if not role_can(code, action):
            raise BizError("forbidden", f"当前角色（{code}）无权执行该操作")
        return user
    return guard
