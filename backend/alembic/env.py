import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context

# 把 backend 目录加到 sys.path，让 app 模块可导入
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base
from app.config import settings
# 导入所有模型以注册到 Base.metadata
from app.models import user  # noqa: F401
from app.models import node, tag, relationship, source, chat  # noqa: F401

config = context.config

# 默认使用项目配置；测试和部署编排可显式传入隔离的连接串。
database_url = config.attributes.get("database_url", settings.database_url)
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
