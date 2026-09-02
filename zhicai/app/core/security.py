# -*- coding: utf-8 -*-
"""会话认证与密码（项目书 4.1：自研 session，itsdangerous 签名 cookie；pbkdf2 存密码）。"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer

from .config import CONFIG

_serializer = URLSafeSerializer(CONFIG.session_secret, salt="zhicai-session")

# cookie 名
SESSION_COOKIE = "zhicai_session"
BOOK_COOKIE = "zhicai_book"

# 角色（对标 Odoo res.groups，M1 预置三个）
ROLES = ("admin", "accountant", "viewer")


# ---------- 密码 ----------
def hash_password(password: str) -> str:
    """pbkdf2_sha256，格式：pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>"""
    iterations = 60000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ---------- 会话 ----------
def create_session_token(user_id: int) -> str:
    payload = {
        "uid": user_id,
        "exp": (datetime.now(timezone.utc) + timedelta(hours=CONFIG.session_expire_hours)).isoformat(),
    }
    return _serializer.dumps(payload)


def parse_session_token(token: str) -> int | None:
    """校验签名与过期，返回 user_id 或 None。"""
    try:
        payload = _serializer.loads(token)
    except (BadSignature, SignatureExpired):
        return None
    exp = payload.get("exp")
    if exp and datetime.fromisoformat(exp) < datetime.now(timezone.utc):
        return None
    uid = payload.get("uid")
    return int(uid) if uid else None


# ---------- 权限 ----------
def role_can(role_code: str, action: str) -> bool:
    """粗粒度权限矩阵（M1：admin 全权 / accountant 读写无删除 / viewer 只读）。"""
    if role_code == "admin":
        return True
    if role_code == "accountant":
        return action in ("read", "write", "create")
    if role_code == "viewer":
        return action == "read"
    return False
