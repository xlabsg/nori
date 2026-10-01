# Backend

一个 Python 包 finance_agent，使用 API、Worker、Scheduler 三个独立进程入口。共享模块和数据库，不重复实现任务、权限或金融计算。

src/finance_agent/entrypoints/ 负责启动与依赖装配；modules/ 放业务逻辑；adapters/ 放数据库、模型和执行工具集成。迁移仅由 migrations/ 管理。

本地原型使用 FastAPI、Pydantic 与 SQLite，依赖固定在根目录 uv.lock。启动与验证命令见根 README。当前 Worker 仅执行有界的本地快照分析，租约为 60 秒；后续长任务需加入心跳续约。
