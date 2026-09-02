# -*- coding: utf-8 -*-
"""运行配置：读取项目根 config.yaml，不存在则生成默认值（项目书 4.3）。"""
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # zhicai/
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DATA_DIR = PROJECT_ROOT / "data"


@dataclass
class Config:
    host: str = "127.0.0.1"          # 仅监听本机（安全默认）
    port: int = 8000
    db_path: str = str(DATA_DIR / "zhicai.db")
    attachments_dir: str = str(DATA_DIR / "attachments")
    backup_dir: str = ""             # OneDrive 备份目录，首次向导设置；空 = 暂不备份
    backup_keep_copies: int = 90
    session_secret: str = field(default_factory=lambda: secrets.token_hex(32))
    session_expire_hours: int = 12


def load_config() -> Config:
    """加载配置；首次运行自动写默认 config.yaml。"""
    defaults = {
        "host": "127.0.0.1",
        "port": 8000,
        "db_path": str((DATA_DIR / "zhicai.db").as_posix()),
        "attachments_dir": str((DATA_DIR / "attachments").as_posix()),
        "backup_dir": "",
        "backup_keep_copies": 90,
        "session_expire_hours": 12,
    }
    if not CONFIG_PATH.exists():
        raw = dict(defaults)
        raw["session_secret"] = secrets.token_hex(32)
        CONFIG_PATH.write_text(
            yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    else:
        raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        merged = {**defaults, **raw}
        # 会话密钥缺失则补一个并回写
        if not merged.get("session_secret"):
            merged["session_secret"] = secrets.token_hex(32)
            CONFIG_PATH.write_text(
                yaml.safe_dump(merged, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        raw = merged
    cfg = Config()
    for k in ("host", "port", "db_path", "attachments_dir", "backup_dir",
              "backup_keep_copies", "session_secret", "session_expire_hours"):
        if k in raw and raw[k] is not None:
            setattr(cfg, k, raw[k])
    # 确保数据目录存在
    Path(cfg.db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(cfg.attachments_dir).mkdir(parents=True, exist_ok=True)
    return cfg


CONFIG = load_config()

# 环境变量覆盖（测试隔离用：ZC_DB_PATH 指向临时库）
_env_db = os.environ.get("ZC_DB_PATH")
if _env_db:
    CONFIG.db_path = _env_db
    Path(_env_db).parent.mkdir(parents=True, exist_ok=True)
