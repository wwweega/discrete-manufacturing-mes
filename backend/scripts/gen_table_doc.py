"""从 SQLAlchemy 元数据生成《数据库设计》文档。

用法::

    python -m scripts.gen_table_doc                 # 输出到 ../../docs/数据库设计.md
    python -m scripts.gen_table_doc --stdout        # 打印到控制台

文档内容完全由 ORM 模型的 ``__doc__`` / ``comment`` 推导，
保证文档与代码永远一致，不会出现"文档写 20 张表、代码只有 12 张"的情况。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Column  # noqa: E402

from app.models import Base  # noqa: E402
from app.models import (  # noqa: E402  # 触发全部模型注册
    equipment,
    inventory,
    master,
    order,
    quality,
    rbac,
    system,
)

#: 模块分组：按模型所属文件归类，与 README 中的"31 张表"口径一致
MODULE_MAP = {
    "app.models.rbac": ("权限与组织", "RBAC"),
    "app.models.master": ("主数据", "MD"),
    "app.models.inventory": ("物料与库存", "MM"),
    "app.models.order": ("生产工单", "PP"),
    "app.models.quality": ("质量管理", "QM"),
    "app.models.equipment": ("设备数采", "EQ"),
    "app.models.system": ("系统支撑", "SYS"),
}

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "数据库设计.md"


def _type_of(col: Column) -> str:
    try:
        text = str(col.type)
    except Exception:  # pragma: no cover
        text = "TEXT"
    return text.replace("COLLATE", "").strip()


def _describe(col: Column) -> str:
    parts = []
    if col.primary_key:
        parts.append("PK")
    if col.foreign_keys:
        parts.append("FK")
    if col.unique:
        parts.append("UQ")
    if not col.nullable:
        parts.append("非空")
    return "/".join(parts) or "-"


def _group_tables() -> dict[str, list]:
    """按模型类所在文件分组（比表名前缀更可靠：sys_user 属于 RBAC 而非系统表）。"""
    by_class: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        by_class[mapper.local_table.name] = cls.__module__

    groups: dict[str, list] = {mod: [] for mod in MODULE_MAP}
    for name, table in Base.metadata.tables.items():
        module = by_class.get(name, "app.models.system")
        groups.setdefault(module, []).append(table)
    return groups


def render() -> str:
    groups = _group_tables()

    lines = [
        "# 数据库设计",
        "",
        "> 本文件由 `backend/scripts/gen_table_doc.py` **自动生成**，",
        "> 内容直接读取 SQLAlchemy 元数据，与代码保持严格一致。请勿手工编辑。",
        "",
        f"业务表合计 **{len(Base.metadata.tables)} 张**（简历口径：20+ 张业务表）。",
        "",
    ]

    total = 0
    for module, (label, prefix) in MODULE_MAP.items():
        tables = sorted(groups.get(module, []), key=lambda t: t.name)
        if not tables:
            continue
        total += len(tables)
        lines += [f"## {label}（{len(tables)} 张）", ""]
        for table in tables:
            comment = table.comment or ""
            lines.append(f"### `{table.name}` {('— ' + comment) if comment else ''}")
            lines.append("")
            lines.append("| 字段 | 类型 | 约束 | 说明 |")
            lines.append("| --- | --- | --- | --- |")
            for col in table.columns:
                lines.append(
                    f"| `{col.name}` | {_type_of(col)} | {_describe(col)} | {col.comment or ''} |"
                )
            if table.indexes:
                idx = "；".join(
                    "`(" + ", ".join(c.name for c in i.columns) + ")`"
                    for i in table.indexes
                )
                lines += ["", f"**索引**：{idx}"]
            lines.append("")
        lines.append("")

    lines += [
        "## 关键约束说明",
        "",
        "* **幂等唯一约束**：`pp_work_report.uk_pp_report_idempotency(work_order_id, "
        "operation_id, idempotency_key)`——数据库层兜底，杜绝重复报工产生脏数据；",
        "* **幂等快照表**：`sys_idempotency.idempotency_key` 唯一，保存请求指纹与响应快照，"
        "同一 Key 重复请求直接回放首次结果；",
        "* **库存不足拦截**：`mm_inventory_stock` 通过行级锁（`locking.py`）+ 事务扣减，"
        "扣减后可用量不得低于 0；",
        "* **工单状态机**：流转合法性由 `order.WORK_ORDER_TRANSITIONS` 单一真源控制，"
        "非法流转在业务层直接拒绝。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:  # pragma: no cover
    parser = argparse.ArgumentParser(description="生成数据库设计文档")
    parser.add_argument("--stdout", action="store_true", help="打印到控制台而非写文件")
    args = parser.parse_args()

    text = render()
    if args.stdout:
        print(text)
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"已生成：{OUTPUT}（共 {len(Base.metadata.tables)} 张表）")


if __name__ == "__main__":  # pragma: no cover
    main()
