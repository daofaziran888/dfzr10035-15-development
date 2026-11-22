"""Schema差异复核领域服务：按字段差异的实际引用关系归并复核分组。

业务链路：
1. 评审一次勾选多条 schema_diff，按「引用差异 / 键映射」连通性归并成复核分组；
   参与同一键映射的字段进入关联组，无键映射引用的字段进入独立组。
2. 复核分组登记采集证据，判断证据是否齐全并能组合出完整定义。
3. 治理报告按复核分组登记待审核证据，一次核验覆盖同一组的全部筛查项。
4. 差异确认待办持有幂等确认凭据，重复提交同一组只更新原待办，不重复发凭据。
5. 批量确认时只有证据齐全的分组可以落库；数据版本按已审核的来源和映射生成。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from app.services.base import BaseModuleService
from app.store import store

REVIEW_DATE = "2026-11-18"


# ---------- 通用解析 ----------

def split_tokens(value: Any) -> list[str]:
    """把逗号/顿号/加号/分号分隔的引用值拆成 token 列表。"""
    if isinstance(value, (list, tuple, set)):
        items: Iterable[Any] = value
    else:
        items = re.split(r"[,，、;；\s+]+", str(value or ""))
    return [str(item).strip() for item in items if str(item).strip() and str(item).strip() != "-"]


def parse_mapping(mapping: Any) -> tuple[list[str], str]:
    """解析「旧键1+旧键2→新键」形式的键映射，返回(旧键列表, 新键)。"""
    text = str(mapping or "").strip()
    if not text:
        return [], ""
    parts = re.split(r"->|=>|＝|→|=", text)
    if len(parts) != 2:
        return [], ""
    olds = [item for item in re.split(r"[+,，、\s]+", parts[0]) if item]
    return olds, parts[1].strip()


def _join(values: Iterable[Any]) -> str:
    return ",".join(str(value) for value in values if str(value or "").strip())


def _collect(ev: dict) -> bool:
    return str(ev.get("采集状态", "")) in {"已采集", "已关联"}


def _evidence_for(endpoint: str, field: str) -> list[dict]:
    rows = []
    for ev in store.rows("diff_evidence"):
        if str(ev.get("关联端点", "")) != endpoint:
            continue
        if field in split_tokens(ev.get("证据字段", "")):
            rows.append(ev)
    return rows


def _credential(endpoint: str, records: list[str], mapping: str) -> str:
    seed = f"{endpoint}|{mapping}|{','.join(sorted(records))}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12].upper()
    return f"CONF-{digest}"


def _evidence_snapshot(endpoint: str, fields: set[str] | None = None) -> list[dict[str, Any]]:
    return [
        {
            "证据编号": ev.get("证据编号", ""),
            "证据字段": ev.get("证据字段", ""),
            "证据类型": ev.get("证据类型", ""),
            "来源样本": ev.get("来源样本", ""),
            "旧键引用": ev.get("旧键引用", ""),
            "样本原值": ev.get("样本原值", ""),
            "采集状态": ev.get("采集状态", ""),
            "采集依据": ev.get("采集依据", ""),
        }
        for ev in store.rows("diff_evidence")
        if str(ev.get("关联端点", "")) == endpoint
        and (not fields or str(ev.get("证据字段", "")) in fields)
    ]


def evaluate_group(group: dict) -> dict[str, Any]:
    """评估分组证据：是否齐全、缺什么、能组合出的完整定义是什么。"""
    endpoint = str(group.get("关联端点", ""))
    mapping = str(group.get("键映射", "") or "")
    olds, new_field = parse_mapping(mapping)
    records = split_tokens(group.get("覆盖差异", ""))
    diffs = [
        diff for diff in store.rows("schema_diff")
        if str(diff.get("记录编号", "")) in records
    ]
    new_diff = next((d for d in diffs if str(d.get("变更字段", "")) == new_field), None)
    missing: list[str] = []
    notes: list[str] = []
    scope_fields: set[str] = set()

    if mapping and olds and new_field:
        scope_fields = set(olds) | {new_field}
        for old in olds:
            candidates = _evidence_for(endpoint, old)
            if not any(_collect(ev) for ev in candidates):
                missing.append(f"{old}:缺少旧键来源样本")
        new_candidates = _evidence_for(endpoint, new_field)
        collected_new = [ev for ev in new_candidates if _collect(ev)]
        if not collected_new:
            missing.append(f"{new_field}:缺少新字段来源样本")
        else:
            covered = set()
            for ev in collected_new:
                covered.update(split_tokens(ev.get("旧键引用", "")))
            uncovered = [old for old in olds if old not in covered]
            if uncovered:
                missing.append(f"{new_field}:来源样本未覆盖旧键{'、'.join(uncovered)}")
            elif not str(collected_new[0].get("样本原值", "")).strip():
                missing.append(f"{new_field}:样本原值为空")
        definition = ""
        if not missing:
            template = str((new_diff or {}).get("新定义", "")).strip()
            if "=" in template:
                definition = template
            else:
                base = template.split("(")[0].strip() if template else f"{new_field}:str"
                if ":" not in base:
                    base = f"{new_field}:str"
                definition = f"{base} = concat({'+'.join(olds)})"
            notes.append(f"按键映射{mapping}组合出完整定义")
    else:
        fields = [field for field in split_tokens(group.get("覆盖字段", "")) ] or [
            str(diff.get("变更字段", "")) for diff in diffs
        ]
        scope_fields = set(fields)
        for field in fields:
            candidates = _evidence_for(endpoint, field)
            if not any(_collect(ev) for ev in candidates):
                missing.append(f"{field}:缺少单列来源样本")
        definition = ""
        if not missing:
            definitions = []
            for field in fields:
                diff = next((d for d in diffs if str(d.get("变更字段", "")) == field), None)
                definitions.append(
                    str((diff or {}).get("新定义", "")).strip() or f"{field}:str"
                )
            definition = "；".join(definitions)
            if len(fields) == 1:
                notes.append(f"字段{fields[0]}无键映射引用，单列样本可独立验证")
            else:
                notes.append(f"字段{'、'.join(fields)}按引用关系联合补采后组合成完整定义")
    return {
        "ready": not missing,
        "missing": missing,
        "definition": definition,
        "notes": notes,
        "evidence": _evidence_snapshot(endpoint, scope_fields),
    }


def _group_status(ready: bool) -> str:
    return "待确认" if ready else "证据不足"


def _evidence_state(ready: bool, missing: list[str]) -> str:
    if ready:
        return "证据齐全"
    return "待补采:" + "；".join(missing)


# ---------- 报告 / 待办登记 ----------

def _upsert_report(group: dict, readiness: dict) -> dict:
    code = f"GOVE-DIFF-{int(group['id']):04d}"
    rows = store.rows("govern_report")
    report = next((row for row in rows if row.get("报告编号") == code), None)
    evidence_text = _join(
        f"{ev['证据字段']}={ev['样本原值'] or '空'}({ev['采集状态']})"
        for ev in readiness["evidence"]
    ) or "尚无采集证据"
    pending_text = "；".join(readiness["missing"]) or "证据齐全，可提交核验"
    if report is None:
        report = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "报告编号": code,
            "评估范围": f"差异复核:{group.get('关联端点', '')}",
            "合规指标": "Schema差异复核证据完整性",
            "当前得分": 60.0,
            "改进事项": "",
            "评估周期": "2026-Q4",
            "负责人": "数据架构组",
            "生成时间": REVIEW_DATE,
            "status": "待生成",
            "pending": True,
            "abnormal": False,
            "复核分组": group.get("分组编号", ""),
            "复核类型": group.get("复核类型", ""),
            "覆盖差异": group.get("覆盖差异", ""),
            "核验凭据": group.get("确认凭据", ""),
            "证据状态": group.get("证据状态", ""),
        }
        rows.append(report)
    report["评估范围"] = (
        f"差异复核:{group.get('关联端点', '')}/"
        f"{group.get('复核类型', '')}/{group.get('覆盖差异', '')}"
    )
    report["改进事项"] = f"待核验筛查项:{group.get('覆盖差异', '')}；{pending_text}"
    report["复核分组"] = group.get("分组编号", "")
    report["复核类型"] = group.get("复核类型", "")
    report["覆盖差异"] = group.get("覆盖差异", "")
    report["核验凭据"] = group.get("确认凭据", "")
    report["证据状态"] = group.get("证据状态", "")
    report["待审证据"] = evidence_text
    report["证据明细"] = readiness["evidence"]
    if str(report.get("status")) != "已审核":
        report["status"] = "待生成"
        report["pending"] = True
    return report


def _upsert_todo(group: dict, readiness: dict) -> dict:
    rows = store.rows("diff_confirmation")
    group_id = int(group["id"])
    todo = next(
        (row for row in rows if str(row.get("确认凭据", "")) == str(group.get("确认凭据", ""))),
        None,
    )
    if todo is None:
        todo = next((row for row in rows if int(row.get("复核分组") or 0) == group_id), None)
    if todo is None:
        todo = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "待办编号": f"CONF-DIFF-{group_id:04d}",
            "复核分组": group_id,
            "关联端点": group.get("关联端点", ""),
            "复核类型": group.get("复核类型", ""),
            "覆盖差异": group.get("覆盖差异", ""),
            "确认凭据": group.get("确认凭据", ""),
            "证据状态": "",
            "审核结论": "待确认",
            "已确认字段": "",
            "落库版本": "",
            "提交时间": REVIEW_DATE,
            "确认时间": "",
            "status": "待确认",
            "pending": True,
            "abnormal": False,
        }
        rows.append(todo)
    if str(todo.get("status")) in {"已作废", "已确认"}:
        return todo
    todo["关联端点"] = group.get("关联端点", "")
    todo["复核类型"] = group.get("复核类型", "")
    todo["覆盖差异"] = group.get("覆盖差异", "")
    todo["确认凭据"] = group.get("确认凭据", "")
    todo["证据状态"] = group.get("证据状态", "")
    todo["status"] = _group_status(readiness["ready"])
    todo["pending"] = True
    todo["审核结论"] = "通过待确认" if readiness["ready"] else "待补采：" + "；".join(readiness["missing"])
    return todo


def _refresh_group(group: dict, readiness: dict) -> None:
    confirmed = str(group.get("status")) == "已确认"
    group["证据状态"] = _evidence_state(readiness["ready"], readiness["missing"])
    group["待补采项"] = "；".join(readiness["missing"])
    if readiness["definition"]:
        group["组合定义"] = readiness["definition"]
    if not confirmed:
        group["status"] = _group_status(readiness["ready"])
        group["pending"] = True
        group["abnormal"] = not readiness["ready"]


def submit_group(group: dict) -> tuple[dict, str, dict]:
    """提交/重提一个复核分组：重算证据、刷新报告与确认待办。"""
    readiness = evaluate_group(group)
    _refresh_group(group, readiness)
    report = _upsert_report(group, readiness)
    todo = _upsert_todo(group, readiness)
    if readiness["ready"]:
        message = f"复核分组{group.get('分组编号')}证据齐全，已交给同一次核验（待办{todo.get('待办编号')}）"
    else:
        message = f"复核分组{group.get('分组编号')}证据不足：{'；'.join(readiness['missing'])}"
    return group, message, {"report": report, "todo": todo, "readiness": readiness}


# ---------- 分组归并 ----------

def _components(diffs: list[dict]) -> list[list[dict]]:
    """按引用差异字段求连通分量；引用关系就是差异之间的实际关联。"""
    by_record = {str(diff.get("记录编号", "")): diff for diff in diffs}
    by_id = {str(diff.get("id", "")): diff for diff in diffs}
    parent = {key: key for key in by_record}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for record, diff in by_record.items():
        for ref in split_tokens(diff.get("引用差异", "")):
            target = by_record.get(ref) or by_id.get(ref)
            if target is not None:
                union(record, str(target.get("记录编号", "")))

    buckets: dict[str, list[dict]] = {}
    for record, diff in by_record.items():
        buckets.setdefault(find(record), []).append(diff)
    return list(buckets.values())


def build_review_groups(diff_ids: list[int]) -> tuple[list[dict], list[str], str]:
    """把一次提交选中的差异按端点和引用关系归并成复核分组。"""
    diffs: list[dict] = []
    problems: list[str] = []
    for raw_id in diff_ids:
        try:
            entry_id = int(raw_id)
        except (TypeError, ValueError):
            problems.append(f"差异编号{raw_id}不合法")
            continue
        diff = store.find("schema_diff", entry_id)
        if diff is None:
            problems.append(f"差异记录{entry_id}不存在")
            continue
        diffs.append(diff)
    if not diffs:
        return [], problems or ["未选择任何差异记录"], ""

    groups: list[dict] = []
    endpoints: dict[str, list[dict]] = {}
    for diff in diffs:
        endpoints.setdefault(str(diff.get("关联端点", "")), []).append(diff)

    for endpoint, subset in endpoints.items():
        for component in _components(subset):
            component.sort(key=lambda item: str(item.get("记录编号", "")))
            records = [str(item.get("记录编号", "")) for item in component]
            fields = [str(item.get("变更字段", "")) for item in component]
            mapping = next(
                (str(item.get("键映射", "")).strip() for item in component
                 if str(item.get("键映射", "")).strip()),
                "",
            )
            related = len(component) > 1 or bool(mapping)
            credential = _credential(endpoint, records if not mapping else [], mapping)
            group_rows = store.rows("diff_review_group")
            group = next(
                (row for row in group_rows if str(row.get("确认凭据", "")) == credential),
                None,
            )
            if group is None and mapping:
                # 批次中断后只重提部分关联差异：沿用同一键映射的既有分组，不另起一组。
                group = next(
                    (
                        row for row in group_rows
                        if str(row.get("关联端点", "")) == endpoint
                        and str(row.get("键映射", "")) == mapping
                        and str(row.get("status")) not in {"已作废", "已确认"}
                    ),
                    None,
                )
                if group is not None:
                    credential = str(group.get("确认凭据", ""))
            if group is None:
                next_id = max((int(row.get("id", 0)) for row in group_rows), default=0) + 1
                group = {
                    "id": next_id,
                    "status": "待核验",
                    "pending": True,
                    "abnormal": False,
                    "分组编号": f"DRG-{next_id:04d}",
                    "关联端点": endpoint,
                    "复核类型": "关联组" if related else "独立组",
                    "键映射": mapping,
                    "覆盖差异": _join(records),
                    "覆盖字段": _join(fields),
                    "证据状态": "待核验",
                    "组合定义": "",
                    "确认凭据": credential,
                    "归并依据": (
                        f"选中差异经引用差异连通，共享键映射{mapping}，必须合并核验"
                        if related and mapping
                        else (
                            "选中差异之间存在引用差异关系，须作为一组核验"
                            if related
                            else f"字段{fields[0] if fields else ''}无键映射引用，单列可独立验证"
                        )
                    ),
                    "补采依据": (
                        "键映射两端字段组合成完整定义，原字段样本与新字段样本合并补采"
                        if related and mapping
                        else (
                            "引用关系内的字段联合补采"
                            if related
                            else f"字段{fields[0] if fields else ''}脱离关联组单独补采，样本单列可独立验证"
                        )
                    ),
                    "分组时间": REVIEW_DATE,
                }
                group_rows.append(group)
            else:
                # 分组已存在（重复提交或中断后重提）：补齐覆盖范围，确认凭据保持不变。
                merged_records = split_tokens(group.get("覆盖差异", ""))
                for record in records:
                    if record not in merged_records:
                        merged_records.append(record)
                merged_fields = split_tokens(group.get("覆盖字段", ""))
                for field in fields:
                    if field not in merged_fields:
                        merged_fields.append(field)
                group["覆盖差异"] = _join(sorted(merged_records))
                group["覆盖字段"] = _join(merged_fields)
                if mapping:
                    group["键映射"] = mapping
                    group["复核类型"] = "关联组"
            groups.append(group)

    for group in groups:
        submit_group(group)
    credential_list = _join(sorted({str(group.get("确认凭据", "")) for group in groups}))
    return groups, problems, credential_list


# ---------- 差异确认 ----------

def _ensure_version(group: dict) -> dict:
    code = f"DATA-DIFF-{int(group['id']):04d}"
    rows = store.rows("data_version")
    exists = next((row for row in rows if row.get("版本编号") == code), None)
    if exists is not None:
        return exists
    records = split_tokens(group.get("覆盖差异", ""))
    diffs = [
        diff for diff in store.rows("schema_diff")
        if str(diff.get("记录编号", "")) in records
    ]
    old_definition = " + ".join(
        str(diff.get("旧定义", "")) for diff in diffs if str(diff.get("旧定义", "")).strip()
    )
    version = {
        "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
        "版本编号": code,
        "数据来源": group.get("关联端点", ""),
        "行数统计": len(records),
        "版本标签": "diff_review_approved",
        "Schema摘要": group.get("组合定义", ""),
        "创建原因": f"差异复核{group.get('确认凭据', '')}确认变更:{group.get('覆盖差异', '')}",
        "依赖版本": old_definition or "无",
        "创建时间": REVIEW_DATE,
        "status": "可用",
        "pending": False,
        "abnormal": False,
        "复核分组": group.get("分组编号", ""),
        "确认凭据": group.get("确认凭据", ""),
        "映射定义": group.get("组合定义", ""),
    }
    rows.append(version)
    return version


def confirm_todos(todo_ids: list[int]) -> dict[str, Any]:
    """批量确认差异确认待办；同组重复提交只认一次确认凭据，证据不足的分组不落库。"""
    results: list[dict[str, Any]] = []
    confirmed_fields: set[str] = set()
    seen_credentials: set[str] = set()
    freshly_confirmed = 0
    for raw_id in todo_ids:
        try:
            todo_id = int(raw_id)
        except (TypeError, ValueError):
            results.append({"待办": raw_id, "结果": "编号不合法"})
            continue
        todo = store.find("diff_confirmation", todo_id)
        if todo is None:
            results.append({"待办": todo_id, "结果": "待办不存在"})
            continue
        credential = str(todo.get("确认凭据", ""))
        if credential and credential in seen_credentials:
            results.append({"待办": todo_id, "待办编号": todo.get("待办编号", ""),
                            "确认凭据": credential, "结果": "重复提交已合并",
                            "说明": "同一确认凭据只确认一次"})
            continue
        seen_credentials.add(credential)
        if str(todo.get("status")) == "已作废":
            results.append({"待办": todo_id, "待办编号": todo.get("待办编号", ""),
                            "结果": "已作废，不再确认"})
            continue
        group = store.find("diff_review_group", int(todo.get("复核分组") or 0))
        if group is None:
            results.append({"待办": todo_id, "待办编号": todo.get("待办编号", ""),
                            "结果": "复核分组不存在"})
            continue
        if str(group.get("status")) == "已确认" or str(todo.get("status")) == "已确认":
            for field in split_tokens(todo.get("已确认字段", "")):
                confirmed_fields.add(field)
            existing = next(
                (row for row in store.rows("data_version")
                 if str(row.get("确认凭据", "")) == credential),
                None,
            )
            results.append({"待办": todo_id, "待办编号": todo.get("待办编号", ""),
                            "确认凭据": credential, "结果": "已确认",
                            "说明": "沿用首次确认凭据，不重复落库",
                            "落库版本": todo.get("落库版本", "") or (existing or {}).get("版本编号", "")})
            continue
        readiness = evaluate_group(group)
        _refresh_group(group, readiness)
        if not readiness["ready"]:
            todo["status"] = "证据不足"
            todo["pending"] = True
            todo["abnormal"] = True
            todo["证据状态"] = group.get("证据状态", "")
            todo["审核结论"] = f"待补采：{'；'.join(readiness['missing'])}"
            _upsert_report(group, readiness)
            results.append({
                "待办": todo_id,
                "待办编号": todo.get("待办编号", ""),
                "确认凭据": todo.get("确认凭据", ""),
                "结果": "待补采",
                "缺失": readiness["missing"],
            })
            continue

        records = split_tokens(group.get("覆盖差异", ""))
        fields = split_tokens(group.get("覆盖字段", ""))
        for diff in store.rows("schema_diff"):
            if str(diff.get("记录编号", "")) in records:
                diff["status"] = "已确认"
                diff["pending"] = False
                diff["abnormal"] = False
        group["status"] = "已确认"
        group["pending"] = False
        group["abnormal"] = False
        group["组合定义"] = readiness["definition"]
        group["证据状态"] = "证据齐全"
        todo["status"] = "已确认"
        todo["pending"] = False
        todo["abnormal"] = False
        todo["证据状态"] = "证据齐全"
        todo["审核结论"] = "通过"
        todo["已确认字段"] = _join(fields)
        todo["确认时间"] = REVIEW_DATE
        version = _ensure_version(group)
        todo["落库版本"] = version.get("版本编号", "")
        report = _upsert_report(group, readiness)
        report["状态"] = "已审核"
        report["status"] = "已审核"
        report["pending"] = False
        report["审核结论"] = "通过"
        for field in fields:
            confirmed_fields.add(field)
        results.append({
            "待办": todo_id,
            "待办编号": todo.get("待办编号", ""),
            "确认凭据": todo.get("确认凭据", ""),
            "结果": "已确认",
            "覆盖字段": fields,
            "落库版本": version.get("版本编号", ""),
            "组合定义": readiness["definition"],
        })
        freshly_confirmed += 1
    ok = any(item.get("结果") == "已确认" for item in results)
    blocked = [item for item in results if item.get("结果") == "待补采"]
    duplicated = [item for item in results if item.get("结果") == "重复提交已合并"]
    reused = sum(
        1 for item in results
        if item.get("结果") == "已确认" and item.get("说明") == "沿用首次确认凭据，不重复落库"
    )
    if freshly_confirmed and blocked:
        message = f"批量确认完成：{freshly_confirmed}组已落库，{len(blocked)}组待补采"
    elif freshly_confirmed:
        message = f"批量确认完成：{freshly_confirmed}组已落库"
    elif reused and not blocked:
        message = f"本次提交均已在此前确认过：{reused}条沿用首次确认凭据，未重复落库"
    elif ok and blocked:
        message = f"本次确认未落库，{len(blocked)}组证据待补采"
    else:
        message = "没有可确认的差异待办"
    if duplicated:
        message += f"；{len(duplicated)}条重复提交按同一确认凭据合并"
    return {
        "ok": ok,
        "message": message,
        "results": results,
        "confirmed_fields": sorted(confirmed_fields),
    }


def workspace(endpoint: str | None = None) -> dict[str, Any]:
    """复核工作台数据：差异、证据、分组、报告、待办、版本全部可回查。"""

    def in_scope(row: dict) -> bool:
        if endpoint:
            key = row.get("关联端点") or row.get("目标端点") or row.get("数据来源") or ""
            if not key:
                key = row.get("评估范围") or ""
            if endpoint not in str(key):
                return False
        return True

    diffs = [row for row in store.rows("schema_diff") if in_scope(row)]
    evidence = [row for row in store.rows("diff_evidence") if in_scope(row)]
    groups = [row for row in store.rows("diff_review_group") if in_scope(row)]
    todos = [row for row in store.rows("diff_confirmation") if in_scope(row)]
    reports = [
        row for row in store.rows("govern_report")
        if "DIFF" in str(row.get("报告编号", "")) and in_scope(row)
    ]
    versions = [
        row for row in store.rows("data_version")
        if str(row.get("版本编号", "")).startswith("DATA-DIFF") and in_scope(row)
    ]
    confirmed_fields = sorted({
        str(diff.get("变更字段", ""))
        for diff in store.rows("schema_diff")
        if str(diff.get("status")) == "已确认"
        and (not endpoint or endpoint in str(diff.get("关联端点", "")))
    })
    return {
        "endpoint": endpoint or "",
        "diffs": diffs,
        "evidence": evidence,
        "groups": groups,
        "todos": todos,
        "reports": reports,
        "versions": versions,
        "confirmed_fields": confirmed_fields,
    }


# ---------- 模块服务 ----------

class DiffEvidenceService(BaseModuleService):
    MODULE = "diff_evidence"
    ENTITY = "采集证据"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["证据编号", "关联端点", "证据字段", "证据类型", "来源样本", "旧键引用",
                   "样本原值", "采集状态", "采集依据", "采集时间"]
    REQUIRED_FIELDS = ["证据编号", "关联端点", "证据字段"]
    STATUS_ORDER = ["待补采", "已采集", "已关联", "已归档"]
    ACTION_RULES = {"确认采信": "已采集", "关联旧键": "已关联", "归档证据": "已归档"}
    NEGATIVE_ACTIONS = []

    def create_entry(self, values: dict[str, Any]):
        """登记样本时保留样本原值，并按是否覆盖多个旧键判定采集状态。"""
        endpoint = str(values.get("关联端点") or "").strip()
        field = str(values.get("证据字段") or "").strip()
        keys = split_tokens(values.get("旧键引用", ""))
        samples = str(values.get("样本原值") or "").strip()
        for existing in store.rows(self.MODULE):
            if (
                str(existing.get("关联端点", "")) == endpoint
                and str(existing.get("证据字段", "")) == field
                and split_tokens(existing.get("旧键引用", "")) == keys
                and str(existing.get("来源样本", "")) == str(values.get("来源样本") or "")
            ):
                if samples and not str(existing.get("样本原值", "")).strip():
                    existing["样本原值"] = samples
                    existing["采集状态"] = "已关联" if len(keys) >= 2 else "已采集"
                    existing["status"] = existing["采集状态"]
                    existing["pending"] = existing["采集状态"] == "待补采"
                return existing, []
        entry, missing = super().create_entry(values)
        if entry is None:
            return entry, missing
        entry["采集状态"] = "已关联" if samples and len(keys) >= 2 else (
            "已采集" if samples else "待补采"
        )
        entry["status"] = entry["采集状态"]
        entry["pending"] = entry["采集状态"] == "待补采"
        entry["采集时间"] = REVIEW_DATE
        entry["采集依据"] = str(values.get("采集依据") or (
            f"字段{field}来源样本经{'、'.join(keys)}交叉核对" if keys else f"字段{field}单列来源样本"
        ))
        return entry, []


class DiffReviewGroupService(BaseModuleService):
    MODULE = "diff_review_group"
    ENTITY = "复核分组"
    OPERATION_TERM = "复核"
    LIST_FIELDS = ["分组编号", "关联端点", "复核类型", "键映射", "覆盖差异", "覆盖字段",
                   "证据状态", "组合定义", "确认凭据", "分组时间"]
    REQUIRED_FIELDS = ["分组编号", "关联端点", "复核类型", "覆盖差异"]
    STATUS_ORDER = ["待核验", "证据不足", "待确认", "已确认"]
    ACTION_RULES = {"提交核验": "待确认", "重提核验": "待确认"}
    NEGATIVE_ACTIONS = []

    def run_action(self, entry_id: int, action: str):
        group = store.find(self.MODULE, entry_id)
        if group is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action in {"提交核验", "重提核验"}:
            group, message, _ = submit_group(group)
            return group, message
        return super().run_action(entry_id, action)


class DiffConfirmationService(BaseModuleService):
    MODULE = "diff_confirmation"
    ENTITY = "差异确认待办"
    OPERATION_TERM = "确认"
    LIST_FIELDS = ["待办编号", "复核分组", "关联端点", "复核类型", "覆盖差异", "确认凭据",
                   "证据状态", "审核结论", "已确认字段", "落库版本", "提交时间", "确认时间"]
    REQUIRED_FIELDS = ["待办编号", "复核分组", "覆盖差异"]
    STATUS_ORDER = ["待确认", "证据不足", "部分确认", "已确认", "已作废"]
    ACTION_RULES = {"确认批次": "已确认", "作废待办": "已作废"}
    NEGATIVE_ACTIONS = ["作废待办"]

    def run_action(self, entry_id: int, action: str):
        todo = store.find(self.MODULE, entry_id)
        if todo is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if action == "确认批次":
            result = confirm_todos([entry_id])
            return todo, result["message"]
        return super().run_action(entry_id, action)
