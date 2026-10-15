"""单 writer 索引执行器。入口显式指定数据库/索引路径，不执行 DDL。"""
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


@contextmanager
def writer_lock(directory: Path):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / ".index-writer.lock").open("a+b")
    acquired = False
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    except OSError as exc:
        if not acquired:
            raise RuntimeError("index writer already active") from exc
        raise
    finally:
        if acquired:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


def run_once(sessions, upsert, remove, *, clock=_now, lease_seconds=900):
    from app.models.index_job import IndexJob
    from app.models.node import KnowledgeNode
    from app.services.index_jobs import claim, complete, enqueue, fail, fingerprint

    with sessions() as db:
        lease = claim(db, now=clock(), lease_seconds=lease_seconds)
        db.commit()
    if lease is None:
        return "idle"
    try:
        with sessions() as db:
            node = db.query(KnowledgeNode).filter_by(
                id=lease.node_id, user_id=lease.user_id).first()
            if node is None:
                payload = None
            else:
                current = fingerprint(node.title, node.content)
                if lease.operation == "delete" or current != lease.source_fingerprint:
                    enqueue(db, node.user_id, node.id, "upsert", current, now=clock())
                    db.commit()
                    return "superseded"
                payload = (node.id, node.content, node.title, node.user_id)
        if payload is None:
            remove(lease.node_id, lease.user_id)
        else:
            upsert(*payload)
        with sessions() as db:
            done = complete(db, lease, now=clock())
            db.commit()
        return "succeeded" if done else "superseded"
    except Exception as exc:  # noqa: BLE001  第三方索引失败只记录类型，交给有限重试。
        with sessions() as db:
            recorded = fail(db, lease, type(exc).__name__, now=clock())
            db.commit()
            job = db.get(IndexJob, (lease.user_id, lease.node_id))
            return job.state if recorded else "superseded"


def main(argv=None):
    import argparse
    import os
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--chroma-dir", type=Path)
    parser.add_argument("--chroma-url", default=os.environ.get('KB_CHROMA_URL', ''))
    parser.add_argument("--lock-dir", type=Path)
    parser.add_argument("--offline-local", action='store_true', help='本地索引仅在API停止后离线更新')
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.chroma_url:
        from app.services.index_store import parse_server_url
        try:
            parse_server_url(args.chroma_url)
        except ValueError as exc:
            parser.error(str(exc))
        if args.chroma_dir is not None or args.offline_local:
            parser.error('HTTP mode does not accept --chroma-dir or --offline-local')
        if args.lock_dir is None or not args.lock_dir.is_absolute():
            parser.error('HTTP mode requires an absolute --lock-dir shared by writers on this host')
        lock_directory = args.lock_dir
    else:
        if not args.offline_local:
            parser.error('local mode requires --offline-local; stop the API before indexing')
        if os.environ.get('APP_ENV') == 'production':
            parser.error('production requires --chroma-url; local index is offline-only')
        if args.chroma_dir is None or not args.chroma_dir.is_absolute():
            parser.error('--chroma-dir must be absolute in local mode')
        if args.lock_dir is not None:
            parser.error('local mode locks --chroma-dir; do not specify --lock-dir')
        lock_directory = args.chroma_dir
    # 在任何 app 配置/存储导入前冻结显式运行配置。
    os.environ["DATABASE_URL"] = args.database_url
    os.environ['KB_CHROMA_URL'] = args.chroma_url
    if args.chroma_dir is not None:
        os.environ["KB_CHROMA_DIR"] = str(args.chroma_dir)
    with writer_lock(lock_directory):
        from app.config import settings
        if settings.kb_chroma_url != args.chroma_url or settings.database_url != args.database_url:
            raise RuntimeError('worker configuration was already loaded; start a fresh process')
        from app.database import SessionLocal
        from app.services import rag_service
        try:
            while True:
                result = run_once(SessionLocal, rag_service.add_node_to_index, rag_service.remove_node_from_index)
                if args.once:
                    return
                if result == "idle":
                    time.sleep(1)
        finally:
            rag_service.chroma_client.close()


if __name__ == "__main__":
    main()
