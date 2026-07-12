# Alembic 基线迁移设计

## 目标

将生产环境的数据库 schema 管理从应用启动时的 `Base.metadata.create_all()` 切换为 Alembic 迁移。迁移必须可审计、可回滚，并允许已有 SQLite 或 MySQL 数据库在不删除、不重建用户数据的前提下纳入版本管理。

## 范围

本阶段建立当前模型的初始基线 revision，并改造部署启动顺序。不会修改既有表字段、删除表、清理数据或自动执行 destructive migration。

## 迁移策略

### 新数据库

`alembic upgrade head` 执行首个 revision，创建当前 SQLAlchemy metadata 中的用户、知识节点、标签、关系、来源、对话、消息和关联表，以及它们的索引和外键。

### 已有数据库

已有数据库已经由历史 `create_all()` 建表，因此不能直接执行会创建同名表的基线 revision。部署前执行只读 schema 校验，确认所有目标表存在且列集合满足当前 metadata；确认后使用 `alembic stamp <baseline_revision>` 写入版本号，不执行 DDL，不接触业务数据。

校验失败时停止部署并显示缺失表或列；不得以删除、drop 或重新初始化数据库的方式“修复”。

## 启动与部署

FastAPI lifespan 仅验证运行时配置，不执行 schema DDL。容器启动命令在启动 Uvicorn 前运行 `alembic upgrade head`；应用进程不需要持续的数据库 DDL 权限。开发者可使用同一 Alembic 命令显式迁移本地数据库。

## 验收

1. 空 SQLite 数据库执行 upgrade 后，`alembic current` 指向 head，应用可完成基本认证与节点读写。
2. 已有 schema 的 SQLite 数据库经校验和 stamp 后，表与数据保持不变，并且 `alembic current` 指向 head。
3. 无法满足当前 schema 的数据库校验失败，且不会写入版本表或修改业务表。
4. 后端全量测试与前端生产构建保持通过。

## 风险与取舍

- 自动迁移仅由部署入口执行，不由每个应用 worker 执行，避免并发抢占 DDL。
- 基线 revision 的 downgrade 仅面向由该 revision 新建的空环境；在包含业务数据的生产库中，回滚需先备份并按照运行手册执行。
- SQLite 与 MySQL 的 schema 差异由 Alembic 的 SQLAlchemy 方言处理；迁移 smoke test 至少覆盖 SQLite，MySQL 在具备服务环境后执行。
