# -*- coding: utf-8 -*-
"""模块注册表（对标 Odoo addons 装载机制与 ir.model 元数据，项目书 5.3.1）。

启动流程：
1. 各模块包暴露 register() -> ModuleDescriptor；
2. Registry.load_all() 按依赖拓扑排序装载（禁止循环依赖）；
3. main.py 拿到全部模型后 create_all 建表；
4. meta API / 前端视图渲染 / CRUD 动态路由都从这里取元数据。

新增一个业务实体的成本 = 一个 SQLAlchemy 模型 + 一份字段元数据 + 一份视图配置。
"""
from dataclasses import dataclass, field as dc_field

from sqlalchemy import ForeignKey, Text
from sqlalchemy.types import (
    BOOLEAN,
    DATE,
    DATETIME,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text as SAText,
)

from .errors import BizError

# SQLAlchemy 类型 → 前端控件类型的默认映射（可被 FIELD_META 覆盖）
_TYPE_MAP = {
    Integer: "integer", BigInteger: "integer", Float: "float",
    Numeric: "decimal", Boolean: "boolean", BOOLEAN: "boolean",
    Date: "date", DATE: "date", DateTime: "datetime", DATETIME: "datetime",
    String: "char", SAText: "text", Text: "text",
}


@dataclass
class ModuleDescriptor:
    """模块描述符（对标 Odoo __manifest__.py）。"""
    name: str                                   # 模块名（目录名）
    label: str                                  # 中文显示名
    depends: list[str]                          # 依赖模块
    menu: list[dict] = dc_field(default_factory=list)
    models: dict[str, type] = dc_field(default_factory=dict)       # 表名 → 模型类
    field_meta: dict[str, dict] = dc_field(default_factory=dict)   # 表名 → 字段元数据
    views: dict[str, dict] = dc_field(default_factory=dict)        # 表名 → 视图配置
    seed_fn: object = None                      # def seed(db) -> None，幂等种子数据


class ModelRegistry:
    """全局模型注册表（进程内单例）。"""

    def __init__(self):
        self.modules: dict[str, ModuleDescriptor] = {}
        self._models: dict[str, type] = {}
        self._field_meta: dict[str, dict] = {}
        self._views: dict[str, dict] = {}
        self._model_to_module: dict[str, str] = {}

    # ---------- 装载 ----------
    def register_module(self, desc: ModuleDescriptor):
        if desc.name in self.modules:
            raise BizError("module_dup", f"模块重复注册：{desc.name}")
        for dep in desc.depends:
            if dep not in self.modules:
                raise BizError("module_dep", f"模块 {desc.name} 依赖未注册的 {dep}")
        self.modules[desc.name] = desc
        for table, cls in desc.models.items():
            if table in self._models:
                raise BizError("model_dup", f"模型表名冲突：{table}")
            self._models[table] = cls
            self._model_to_module[table] = desc.name
        for table, meta in desc.field_meta.items():
            self._field_meta.setdefault(table, {}).update(meta)
        for table, views in desc.views.items():
            self._views.setdefault(table, {}).update(views)

    def topological_order(self, descriptors: dict[str, ModuleDescriptor]) -> list[str]:
        """Kahn 拓扑排序；循环依赖直接报错。"""
        order, visited, temp = [], set(), set()

        def visit(name: str):
            if name in visited:
                return
            if name in temp:
                raise BizError("module_cycle", f"模块循环依赖：{name}")
            temp.add(name)
            for dep in descriptors[name].depends:
                visit(dep)
            temp.discard(name)
            visited.add(name)
            order.append(name)

        for name in descriptors:
            visit(name)
        return order

    # ---------- 查询 ----------
    def model(self, table: str) -> type:
        cls = self._models.get(table)
        if cls is None:
            raise BizError("model_not_found", f"模型不存在：{table}")
        return cls

    def has_model(self, table: str) -> bool:
        return table in self._models

    def model_label(self, table: str) -> str:
        module_name = self._model_to_module.get(table, "")
        module = self.modules.get(module_name)
        views = self._views.get(table, {})
        return views.get("label") or (module.label if module else table)

    def menus(self) -> list[dict]:
        """收集全部模块菜单（按模块装载顺序 = 依赖顺序）。"""
        items = []
        for name in self.topological_order(self.modules):
            for m in self.modules[name].menu:
                m = dict(m)
                m.setdefault("module", name)
                items.append(m)
        return items

    def field_meta_of(self, table: str) -> dict:
        return self._field_meta.get(table, {})

    def views_of(self, table: str) -> dict:
        return self._views.get(table, {})

    def view_config(self, table: str, view_type: str) -> dict:
        v = self._views.get(table, {}).get(view_type)
        if v is None:
            raise BizError("view_not_found", f"模型 {table} 缺少 {view_type} 视图配置")
        return v

    def is_book_scoped(self, table: str) -> bool:
        try:
            return getattr(self.model(table), "_book_scoped", False)
        except BizError:
            return False

    # ---------- 元数据输出（meta API 数据源） ----------
    def describe_model(self, table: str) -> dict:
        """合并 SQLAlchemy 列信息与模块字段元数据，输出前端可消费的完整描述。"""
        cls = self.model(table)
        overrides = self._field_meta.get(table, {})
        fields = {}
        for col in cls.__table__.columns:
            name = col.key
            if name in ("id",):
                fields[name] = {"label": "ID", "type": "integer", "readonly": True}
                continue
            if name in ("create_uid", "create_date", "write_uid", "write_date"):
                labels = {
                    "create_uid": "创建人", "create_date": "创建时间",
                    "write_uid": "修改人", "write_date": "修改时间",
                }
                fields[name] = {"label": labels[name], "type": "datetime" if name.endswith("date") else "integer",
                                "readonly": True, "system": True}
                continue
            ftype = "char"
            for sa_type, mapped in _TYPE_MAP.items():
                if isinstance(col.type, sa_type):
                    ftype = mapped
                    break
            meta = {"label": name, "type": ftype}
            # 外键 → many2one
            fks = list(col.foreign_keys)
            if fks:
                target = list(fks[0].constraint.elements)[0].target_fullname  # "res_book.id"
                meta["type"] = "many2one"
                meta["relation"] = target.split(".")[0]
            # 模块覆盖（label/type/options/required/readonly/help/placeholder）
            meta.update(overrides.get(name, {}))
            if col.nullable is False and "required" not in meta:
                meta["required"] = True
            fields[name] = meta
        # 模块里声明但非列的虚拟字段（如 total_amount 计算展示）也可以塞进 overrides
        for name, meta in overrides.items():
            if name not in fields:
                fields[name] = dict(meta)
        result = {
            "table": table,
            "label": self.model_label(table),
            "module": self._model_to_module.get(table),
            "book_scoped": getattr(cls, "_book_scoped", False),
            "rec_name": getattr(cls, "_rec_name", "name"),
            "fields": fields,
            "views": self._views.get(table, {}),
        }
        return result


REGISTRY = ModelRegistry()
