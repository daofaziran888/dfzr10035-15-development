"""差异复核接口：批量归并复核分组、证据补采、报告/待办联查和批量确认落库。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.services.diff_review import (
    build_review_groups,
    confirm_todos,
    evaluate_group,
    workspace,
)
from app.store import store

router = APIRouter(prefix="/api", tags=["差异复核"])


class DiffBatchPayload(BaseModel):
    diff_ids: list[int] = Field(default_factory=list)
    remark: str | None = None


class ConfirmBatchPayload(BaseModel):
    todo_ids: list[int] = Field(default_factory=list)
    credential: str | None = None
    remark: str | None = None


class EvidencePayload(BaseModel):
    endpoint: str
    field: str
    sample: str = ""
    old_keys: str = ""
    evidence_type: str = "补采样本"
    source: str = ""


@router.post("/schema_diff/review/batch")
def review_batch(payload: DiffBatchPayload) -> dict:
    """批量选择差异后按引用关系归并分组，并登记治理报告与差异确认待办。"""
    groups, problems, credential = build_review_groups(payload.diff_ids)
    if not groups:
        return {
            "ok": False,
            "message": "；".join(problems) or "没有可归并的差异记录",
            "groups": [],
            "problems": problems,
        }
    related = sum(1 for group in groups if group.get("复核类型") == "关联组")
    standalone = len(groups) - related
    message = (
        f"已归并{len(groups)}个复核分组（关联组{related}个/独立组{standalone}个），"
        "治理报告已按分组登记待审证据，确认待办已生成"
    )
    if problems:
        message += f"；跳过：{'；'.join(problems)}"
    return {
        "ok": True,
        "message": message,
        "credentials": credential,
        "groups": groups,
        "problems": problems,
    }


@router.get("/schema_diff/review/workspace")
def review_workspace(endpoint: str | None = Query(default=None)) -> dict:
    """复核工作台：分组、证据、报告、待办、数据版本与已确认字段统一回查。"""
    return workspace(endpoint)


@router.get("/diff_review_group/{group_id}/readiness")
def group_readiness(group_id: int) -> dict:
    """单个分组的证据齐全度、缺失项和组合定义。"""
    group = store.find("diff_review_group", group_id)
    if group is None:
        return {"ok": False, "message": f"复核分组 {group_id} 不存在"}
    readiness = evaluate_group(group)
    return {"ok": True, "group": group, **readiness}


@router.post("/diff_confirmation/batch")
def confirm_batch(payload: ConfirmBatchPayload) -> dict:
    """批量确认差异待办；同组重复提交只认一次确认凭据，只有证据齐全的分组落库。"""
    return confirm_todos(payload.todo_ids)


@router.post("/diff_evidence/review")
def add_evidence(payload: EvidencePayload) -> dict:
    """补采样本：同一端点同一字段的样本按旧键引用归并，重提分组后可重新核验。"""
    from app.services.diff_review import DiffEvidenceService

    service = DiffEvidenceService()
    field = payload.field.strip()
    old_keys = payload.old_keys.strip()
    evidence_type = payload.evidence_type or ("旧键来源样本" if old_keys else "补采样本")
    entry, missing = service.create_entry({
        "证据编号": f"EV-{payload.endpoint or 'UNKNOWN'}-{field}-{len(store.rows('diff_evidence')) + 1}",
        "关联端点": payload.endpoint,
        "证据字段": field,
        "证据类型": evidence_type,
        "来源样本": payload.source or f"{payload.endpoint}:{field}",
        "旧键引用": old_keys,
        "样本原值": payload.sample,
        "采集状态": "已采集" if payload.sample else "待补采",
        "采集依据": (
            f"字段{field}补采样本覆盖旧键{old_keys}，用于组合出完整定义"
            if old_keys else f"字段{field}脱离关联组单独补采，单列可独立验证"
        ),
        "采集时间": "2026-11-18",
    })
    if missing:
        return {"ok": False, "message": f"缺少必填字段：{'、'.join(missing)}"}
    group_id = 0
    for group in store.rows("diff_review_group"):
        if (
            str(group.get("关联端点", "")) == payload.endpoint
            and field in set(
                token.strip(" :") for token in str(group.get("覆盖字段", "")).split(",")
            )
        ):
            group_id = int(group.get("id", 0))
            break
    return {
        "ok": True,
        "message": f"字段{field}证据已登记，复核分组{group_id or '（未归并）'}可重提核验",
        "entry": entry,
        "group_id": group_id,
    }
