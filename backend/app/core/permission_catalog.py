"""权限 Constants 与初始化。"""

from __future__ import annotations

PERMISSIONS: list[tuple[str, str, str, bool]] = [
    # (权限码, 名称, 模块, 是否写操作)
    ("dashboard:view", "查看车间看板", "看板", False),
    ("master:view", "查看基础数据", "基础数据", False),
    ("master:manage", "维护基础数据", "基础数据", True),
    ("order:view", "查看生产工单", "工单", False),
    ("order:create", "创建生产工单", "工单", True),
    ("order:release", "下达生产工单", "工单", True),
    ("order:start", "开工生产工单", "工单", True),
    ("order:complete", "完工生产工单", "工单", True),
    ("order:cancel", "作废生产工单", "工单", True),
    ("order:report", "工序报工", "工单", True),
    ("equipment:view", "查看设备状态", "设备", False),
    ("quality:view", "查看质检单", "质量", False),
    ("quality:create", "发起质检", "质量", True),
    ("quality:handle", "处理质检结论", "质量", True),
    ("inventory:view", "查看库存", "库存", False),
    ("inventory:issue", "工单发料", "库存", True),
    ("inventory:adjust", "库存盘点点调", "库存", True),
    ("spc:view", "查看控制图", "质量", False),
    ("spc:analyze", "录入 SPC 样本", "质量", True),
    ("report:view", "查看统计报表", "报表", False),
    ("system:admin", "系统管理", "系统", True),
]

ROLES: list[tuple[str, str, str]] = [
    ("admin", "管理员", "拥有全部接口权限，负责基础数据与系统配置"),
    ("line_leader", "班组长", "负责工单下达、报工审核、质检处理与报表查看"),
    ("operator", "操作工", "仅能查看自身相关工单并执行工序报工"),
]

#: 角色 → 权限码
ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "admin": tuple(code for code, *_ in PERMISSIONS),
    "line_leader": (
        "dashboard:view", "master:view",
        "order:view", "order:create", "order:release", "order:start",
        "order:complete", "order:cancel", "order:report",
        "equipment:view",
        "quality:view", "quality:create", "quality:handle",
        "inventory:view", "inventory:issue", "inventory:adjust",
        "spc:view", "spc:analyze", "report:view",
    ),
    "operator": (
        "dashboard:view", "order:view", "order:report",
        "equipment:view", "quality:view", "inventory:view",
    ),
}

#: 演示账号（密码均为 mes@2026）
DEMO_USERS: list[tuple[str, str, str, str, str]] = [
    # (账号, 姓名, 工号, 邮箱, 角色)
    ("admin", "系统管理员", "EMP001", "admin@mes.demo", "admin"),
    ("leader", "王班组长", "EMP002", "leader@mes.demo", "line_leader"),
    ("worker", "李操作工", "EMP003", "worker@mes.demo", "operator"),
]

DEMO_PASSWORD = "mes@2026"
