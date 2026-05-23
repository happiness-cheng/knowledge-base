from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

# 根据数据库类型设置不同的连接参数
is_sqlite = settings.database_url.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        settings.database_url,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_nocase(dbapi_conn, connection_record):
        dbapi_conn.create_collation("NOCASE", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
else:
    # MySQL / 其他数据库
    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,  # 1小时回收连接，避免 MySQL wait_timeout 断连
    )

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def nocase(column):
    """大小写不敏感查询：SQLite 用 NOCASE 校对，MySQL 默认就是不敏感"""
    if is_sqlite:
        return column.collate("NOCASE")
    return column
