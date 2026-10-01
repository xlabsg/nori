# Database migrations

唯一数据库迁移目录。本地 SQLite 原型由 finance-admin 显式应用编号 SQL，版本保存在 schema_migrations，迁移与版本登记位于同一事务。失败直接中断，API 不自动建表。当前解析器只支持不包含存储过程的简单 SQL。

接入 PostgreSQL 时迁移到 Alembic，不通过 create_all 或静默忽略错误代替正式迁移。
