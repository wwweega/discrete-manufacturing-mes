"""离散制造车间生产管理系统（MES 方向）后端应用。

分层结构（严格三层，禁止跨层调用）：:

    API 层      app/api/v1/*.py     参数校验、鉴权声明、响应装配
                  │
    服务层      app/services/*.py   状态机、事务边界、业务编排（唯一可写状态的地方）
                  │
    数据访问层  app/repositories/*.py  SQL 封装、复杂查询、分页
                  │
    模型层      app/models/*.py     31 张业务表 ORM 映射
"""

__version__ = "1.0.0"
