# -*- coding: utf-8 -*-
"""base 模块种子数据：角色、admin 账号、默认参数（幂等）。"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.security import hash_password
from .models import IrConfig, ResRole, ResUsers

ADMIN_DEFAULT_PASSWORD = "admin123"  # README 提示首次登录后修改

DEFAULT_CONFIGS = {
    "app.name": {"value": "智财代账工作台", "remark": "系统名称"},
    "portal.links": {
        "value": {
            "etax": "https://etax.chinatax.gov.cn",
            "single_window": "https://www.singlewindow.cn",
            "eport": "http://www.ecustoms.cn",
            "safe": "https://asone.safesvc.gov.cn",
        },
        "remark": "政务平台直达链接（可在系统设置修改）",
    },
    "backup.keep_copies": {"value": 90, "remark": "备份保留份数"},
}


def seed(db: Session):
    """幂等种子：角色 ×3、admin 账号、默认参数。"""
    # 角色
    roles = {
        "admin": "管理员（全部权限）",
        "accountant": "会计（记账读写，无系统设置）",
        "viewer": "只读",
    }
    for code, name in roles.items():
        obj = db.execute(select(ResRole).where(ResRole.code == code)).scalar_one_or_none()
        if obj is None:
            db.add(ResRole(code=code, name=name, permissions=json.dumps({"builtin": True})))
    db.flush()  # 角色先落库，admin 账号才能关联

    # admin 账号
    admin_role = db.execute(select(ResRole).where(ResRole.code == "admin")).scalar_one()
    admin = db.execute(select(ResUsers).where(ResUsers.login == "admin")).scalar_one_or_none()
    if admin is None:
        db.add(ResUsers(login="admin", name="管理员", password_hash=hash_password(ADMIN_DEFAULT_PASSWORD),
                        role_id=admin_role.id))
    elif not admin.role_id:
        admin.role_id = admin_role.id

    # 默认参数
    for key, item in DEFAULT_CONFIGS.items():
        obj = db.execute(select(IrConfig).where(IrConfig.key == key)).scalar_one_or_none()
        if obj is None:
            db.add(IrConfig(key=key, value=json.dumps(item["value"], ensure_ascii=False),
                            remark=item.get("remark")))
    db.flush()
