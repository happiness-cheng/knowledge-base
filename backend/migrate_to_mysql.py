"""
从 SQLite 迁移到 MySQL
用法: venv/Scripts/python.exe migrate_to_mysql.py
前提: XAMPP 的 MySQL 已启动（端口 3306）
"""
import sqlite3
import pymysql
import os
import sys

# MySQL 配置
MYSQL_HOST = "127.0.0.1"
MYSQL_PORT = 3306
MYSQL_USER = "root"
MYSQL_PASS = ""
MYSQL_DB = "knowledge_base"

# SQLite 路径
SQLITE_DB = os.path.join(os.path.expanduser("~"), ".knowledge_base", "knowledge.db")


def create_mysql_database():
    """创建 MySQL 数据库（如果不存在）"""
    conn = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASS,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"[OK] MySQL 数据库 `{MYSQL_DB}` 已就绪")
    finally:
        conn.close()


def create_tables():
    """用 SQLAlchemy 在 MySQL 中创建所有表"""
    # 临时覆盖 DATABASE_URL，让 config 读 MySQL
    os.environ["DATABASE_URL"] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"

    # 重新加载 config
    import importlib
    import app.config
    importlib.reload(app.config)

    import app.database
    importlib.reload(app.database)

    from app.database import Base, engine
    # 导入所有模型以注册到 Base.metadata
    from app.models import node, tag, relationship, chat  # noqa

    Base.metadata.create_all(bind=engine)
    print("[OK] MySQL 表已创建")


def migrate_data():
    """从 SQLite 复制数据到 MySQL"""
    if not os.path.exists(SQLITE_DB):
        print(f"[SKIP] SQLite 数据库不存在: {SQLITE_DB}")
        return

    # 连接 SQLite
    src = sqlite3.connect(SQLITE_DB)
    src.row_factory = sqlite3.Row

    # 连接 MySQL
    dst = pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASS,
        database=MYSQL_DB, charset="utf8mb4",
        autocommit=False,
    )

    # 迁移顺序：先主表，再关联表
    tables = [
        "tags",
        "knowledge_nodes",
        "conversations",
        "node_tags",           # 关联表
        "relationships",
        "messages",
        "message_sources",     # 关联表
    ]

    total_rows = 0
    for table in tables:
        try:
            rows = src.execute(f"SELECT * FROM [{table}]").fetchall()
            if not rows:
                print(f"  {table}: 0 行，跳过")
                continue

            columns = [desc[0] for desc in src.execute(f"SELECT * FROM [{table}]").description]
            placeholders = ", ".join(["%s"] * len(columns))
            col_list = ", ".join([f"`{c}`" for c in columns])
            sql = f"INSERT IGNORE INTO `{table}` ({col_list}) VALUES ({placeholders})"

            inserted = 0
            with dst.cursor() as cur:
                for row in rows:
                    values = [row[c] for c in columns]
                    try:
                        cur.execute(sql, values)
                        inserted += 1
                    except Exception as e:
                        print(f"  警告: {table} 某行插入失败: {e}")
            dst.commit()
            total_rows += inserted
            print(f"  {table}: {inserted}/{len(rows)} 行迁移成功")
        except Exception as e:
            print(f"  {table}: 跳过 ({e})")

    src.close()
    dst.close()
    print(f"\n[OK] 迁移完成，共 {total_rows} 行")


def update_env():
    """更新 .env 文件，切换到 MySQL"""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    mysql_url = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"

    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("DATABASE_URL="):
                    lines.append(f"DATABASE_URL={mysql_url}\n")
                    found = True
                else:
                    lines.append(line)

    if not found:
        lines.append(f"DATABASE_URL={mysql_url}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"[OK] .env 已更新: DATABASE_URL → MySQL")
    print(f"     重启后端后生效。要切回 SQLite，删除 .env 中的 DATABASE_URL 行即可")


if __name__ == "__main__":
    print("=== SQLite → MySQL 迁移工具 ===\n")
    try:
        create_mysql_database()
        create_tables()
        migrate_data()
        update_env()
        print("\n=== 迁移成功！重启后端生效 ===")
    except pymysql.err.OperationalError as e:
        if "Can't connect" in str(e):
            print(f"\n[ERROR] 无法连接 MySQL，请确认 XAMPP 的 MySQL 已启动")
            print(f"        错误: {e}")
        else:
            raise
