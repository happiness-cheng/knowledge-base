"""生产存储地址明确，HTTP失败禁止回退本地索引。"""
from unittest.mock import Mock

import pytest

from app.services import index_store


def test_production_requires_server_before_creating_local_state(tmp_path, monkeypatch):
    local = Mock()
    monkeypatch.setattr(index_store.chromadb, 'PersistentClient', local)
    path = tmp_path/'must-not-create'
    with pytest.raises(ValueError, match='KB_CHROMA_URL'):
        index_store.create_index_client(path, url='', production=True)
    assert not path.exists()
    local.assert_not_called()


@pytest.mark.parametrize(('url', 'host', 'port', 'ssl'), [
    ('http://127.0.0.1:8000', '127.0.0.1', 8000, False),
    ('https://index.example/', 'index.example', 443, True),
    ('http://localhost', 'localhost', 80, False),
])
def test_http_configuration_does_not_create_local_index(tmp_path, monkeypatch, url, host, port, ssl):
    factory, local = Mock(), Mock()
    monkeypatch.setattr(index_store.chromadb, 'HttpClient', factory)
    monkeypatch.setattr(index_store.chromadb, 'PersistentClient', local)
    path = tmp_path/'unused'
    assert index_store.create_index_client(path, url=url, production=True) is factory.return_value
    assert factory.call_args.kwargs['host'] == host
    assert factory.call_args.kwargs['port'] == port
    assert factory.call_args.kwargs['ssl'] == ssl
    assert not path.exists()
    local.assert_not_called()


@pytest.mark.parametrize('url', [
    'file:///index', 'index.example:8000', 'http://operator:PRIVATE@index.example',
    'http://index.example?key=PRIVATE', 'http://index.example#PRIVATE',
    'http://index.example/path', 'http://index.example:0', 'http://index.example:65536',
    'http://index.example:abc', 'http://', 'http://[invalid',
])
def test_invalid_address_is_sanitized_without_any_client(tmp_path, monkeypatch, url):
    http, local = Mock(), Mock()
    monkeypatch.setattr(index_store.chromadb, 'HttpClient', http)
    monkeypatch.setattr(index_store.chromadb, 'PersistentClient', local)
    with pytest.raises(ValueError, match='KB_CHROMA_URL') as error:
        index_store.create_index_client(tmp_path/'unused', url=url, production=False)
    assert 'PRIVATE' not in str(error.value)
    http.assert_not_called()
    local.assert_not_called()


def test_unavailable_http_does_not_fall_back(tmp_path, monkeypatch):
    local = Mock()
    monkeypatch.setattr(index_store.chromadb, 'HttpClient', Mock(side_effect=OSError('fixture unavailable')))
    monkeypatch.setattr(index_store.chromadb, 'PersistentClient', local)
    with pytest.raises(OSError):
        index_store.create_index_client(tmp_path/'unused', url='http://127.0.0.1:8000', production=False)
    local.assert_not_called()
    assert not (tmp_path/'unused').exists()


def test_development_without_server_keeps_local_mode(tmp_path, monkeypatch):
    local = Mock()
    monkeypatch.setattr(index_store.chromadb, 'PersistentClient', local)
    assert index_store.create_index_client(tmp_path/'local', url='', production=False) is local.return_value
    assert (tmp_path/'local').is_dir()
