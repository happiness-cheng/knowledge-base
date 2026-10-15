"""worker入口在打开索引/数据库前拒绝不可靠的本地在线拓扑。"""
import sys
from unittest.mock import Mock

import pytest

from app.config import settings
from app.services import index_worker, rag_service


def arguments(monkeypatch, values):
    monkeypatch.setattr(sys, 'argv', ['index_worker', *values])
    # main会固定这些环境；显式纳入monkeypatch恢复范围。
    for name in ('DATABASE_URL', 'KB_CHROMA_DIR', 'KB_CHROMA_URL'):
        monkeypatch.setenv(name, '')


def test_local_writer_requires_offline_ack(tmp_path, monkeypatch, capsys):
    arguments(monkeypatch, ['--database-url', 'sqlite:///:memory:', '--chroma-dir', str(tmp_path), '--once'])
    with pytest.raises(SystemExit) as error:
        index_worker.main()
    assert error.value.code == 2
    assert '--offline-local' in capsys.readouterr().err


def test_http_worker_requires_absolute_lock_directory(monkeypatch, capsys):
    arguments(monkeypatch, ['--database-url', 'sqlite:///:memory:', '--chroma-url', 'http://127.0.0.1:8000',
                           '--lock-dir', 'relative', '--once'])
    with pytest.raises(SystemExit) as error:
        index_worker.main()
    assert error.value.code == 2
    assert 'absolute' in capsys.readouterr().err


def test_http_worker_rejects_local_directory(tmp_path, monkeypatch, capsys):
    arguments(monkeypatch, ['--database-url', 'sqlite:///:memory:', '--chroma-url', 'http://127.0.0.1:8000',
                           '--chroma-dir', str(tmp_path), '--lock-dir', str(tmp_path), '--once'])
    with pytest.raises(SystemExit) as error:
        index_worker.main()
    assert error.value.code == 2
    assert '--chroma-dir' in capsys.readouterr().err


def test_http_worker_once_uses_existing_callbacks_and_closes_client(tmp_path, monkeypatch):
    url = 'http://127.0.0.1:8000'
    arguments(monkeypatch, ['--database-url', 'sqlite:///:memory:', '--chroma-url', url,
                           '--lock-dir', str(tmp_path), '--once'])
    monkeypatch.setattr(settings, 'kb_chroma_url', url)
    monkeypatch.setattr(settings, 'database_url', 'sqlite:///:memory:')
    owner = Mock()
    monkeypatch.setattr(rag_service, 'chroma_client', owner)
    execute = Mock(return_value='idle')
    monkeypatch.setattr(index_worker, 'run_once', execute)
    index_worker.main()
    assert execute.call_args.args[1:] == (rag_service.add_node_to_index, rag_service.remove_node_from_index)
    owner.close.assert_called_once()
    assert not (tmp_path/'chroma.sqlite3').exists()
