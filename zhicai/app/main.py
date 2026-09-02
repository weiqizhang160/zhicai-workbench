# -*- coding: utf-8 -*-
"""FastAPI 应用入口：模块装载 → 建表 → 种子数据 → 路由装配（对标 Odoo 启动流程）。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import (account_api, auth_api, auto_entry_api, bank_api, biz_api,
                  contract_api, crud_api, dashboard_api, documents_api,
                  foreign_trade_api, invoice_api, maintenance_api, meta_api,
                  payroll_api, tasks_api, tax_decl_api)
from .core.db import SessionLocal, engine
from .core.errors import BizError
from .core.registry import REGISTRY, ModuleDescriptor
from .modules import (account, auto_entry, bank, base, board, contract, documents,
                      foreign_trade, invoice, maintenance, payroll, res_partner,
                      tasks, tax_decl)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动钩子：注册模块（依赖拓扑序）→ 建表 → 种子数据。幂等（测试中会多次进入）。"""
    if not REGISTRY.modules:
        descriptors = {
            "base": base.register(),
            "res_partner": res_partner.register(),
            "account": account.register(),
            # —— M3：票据 / 银行 / 自动记账 ——
            "invoice": invoice.register(),
            "bank": bank.register(),
            "auto_entry": auto_entry.register(),
            # —— M4：税务申报台账与日历 ——
            "tax_decl": tax_decl.register(),
            # —— M5：合同收费 / 任务 / 仪表盘 ——
            "contract": contract.register(),
            "tasks": tasks.register(),
            "board": board.register(),
            # —— M6：外贸 / 工资社保 / 文档中心 ——
            "foreign_trade": foreign_trade.register(),
            "payroll": payroll.register(),
            "documents": documents.register(),
            # —— M7：备份与计划任务 ——
            "maintenance": maintenance.register(),
        }
        for name in REGISTRY.topological_order(descriptors):
            REGISTRY.register_module(descriptors[name])

    # 建表（M1：create_all；表结构演进自 M2 起引入 Alembic——README 假设记录）
    from .core.base_model import Base
    Base.metadata.create_all(engine)

    # 种子数据（幂等）
    db = SessionLocal()
    try:
        for name in REGISTRY.topological_order(REGISTRY.modules):
            seed_fn = REGISTRY.modules[name].seed_fn
            if seed_fn:
                seed_fn(db)
        db.commit()
    finally:
        db.close()

    # 计划任务调度线程（M7，项目书 7.13）：启动补跑错过的任务 + 每日定时执行；
    # 测试环境用 ZC_DISABLE_SCHEDULER=1 关闭（conftest 已设置）
    from .modules.maintenance import cron_service
    cron_service.start_scheduler()
    yield


app = FastAPI(title="智财代账工作台", version="0.1.0-M1", lifespan=lifespan)


# ---------- 全局异常：BizError → HTTP ----------
@app.exception_handler(BizError)
async def biz_error_handler(_request: Request, exc: BizError):
    status = 401 if exc.code == "unauthorized" else 400
    return JSONResponse(status_code=status, content={"code": exc.code, "message": exc.message})


# ---------- 路由 ----------
app.include_router(auth_api.router)
app.include_router(meta_api.router)
app.include_router(crud_api.router)
app.include_router(biz_api.router)
app.include_router(account_api.router)
# —— M3：发票 / 银行 / 自动记账 ——
app.include_router(invoice_api.router)
app.include_router(bank_api.router)
app.include_router(auto_entry_api.router)
# —— M4：税务申报 ——
app.include_router(tax_decl_api.router)
# —— M5：合同收费 / 任务 / 仪表盘 ——
app.include_router(contract_api.router)
app.include_router(tasks_api.router)
app.include_router(dashboard_api.router)
# —— M6：外贸 / 工资社保 / 文档中心 ——
app.include_router(foreign_trade_api.router)
app.include_router(payroll_api.router)
app.include_router(documents_api.router)
# —— M7：备份与计划任务 ——
app.include_router(maintenance_api.router)

# ---------- 前端静态资源（无构建，直接服务 static/） ----------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    """SPA 入口。"""
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")
