"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import diff_review, resource

ROUTERS = [diff_review, resource]
