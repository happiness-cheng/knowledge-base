"""仓库内离线验收入口：隔离个人配置、数据与外部网络。"""

import argparse
import builtins
import ipaddress
import json
import os
import socket
import sys
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-isolation', action='store_true')
    parser.add_argument('--empty-model-cache', action='store_true', help='验证测试不依赖个人模型缓存')
    args, pytest_args = parser.parse_known_args(argv)
    backend = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(backend))
    original_open = builtins.open
    original_read = Path.read_text
    original_expanduser = os.path.expanduser
    original_connect = socket.socket.connect
    import httpx
    original_http = httpx.HTTPTransport.handle_request
    original_async_http = httpx.AsyncHTTPTransport.handle_async_request
    protected_files = {
        (backend / '.env').resolve(),
        (Path.home() / '.claude' / 'settings.json').resolve(),
    }

    def guarded_open(path, *args, **kwargs):
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() in protected_files:
            if Path(path).resolve() == (backend / '.env').resolve():
                mode = args[0] if args else kwargs.get('mode', 'r')
                if mode.startswith('r') and '+' not in mode:
                    return BytesIO(b'') if 'b' in mode else StringIO('')
            raise FileNotFoundError('personal configuration excluded from offline tests')
        return original_open(path, *args, **kwargs)

    def guarded_read(path, *args, **kwargs):
        if path.resolve() in protected_files:
            if path.resolve() == (backend / '.env').resolve():
                return ''
            raise FileNotFoundError('personal configuration excluded from offline tests')
        return original_read(path, *args, **kwargs)

    def local_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else ''
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == 'localhost'
        if not local:
            raise RuntimeError('external network disabled in offline tests')
        return original_connect(sock, address)

    def check_http_target(request):
        host = request.url.host
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == 'localhost'
        # 在真实transport上逐跳检查；MockTransport不走网络，也不会被此补丁拦截。
        if not local:
            raise RuntimeError('external network disabled in offline tests')

    def local_http(transport, request):
        check_http_target(request)
        return original_http(transport, request)

    async def local_async_http(transport, request):
        check_http_target(request)
        return await original_async_http(transport, request)

    with TemporaryDirectory(prefix='knowledge-offline-tests-') as temporary_home:
        isolated_home = Path(temporary_home)
        overrides = {
            'ENV_FILE': str(isolated_home / 'absent.env'),
            'DATABASE_URL': 'sqlite:///:memory:',
            'APP_ENV': 'development',
            'AI_API_KEY': '',
            'KB_CHROMA_SUFFIX': '_offline_test',
            'KB_CHROMA_DIR': str(isolated_home / 'chroma'),
            'KB_CHROMA_URL': '',
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
            'ANONYMIZED_TELEMETRY': 'False',
            'NO_PROXY': '*',
            'LANGSMITH_TRACING': 'false',
        }
        overrides.update({name: '' for name in (
            'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy',
        )})
        if args.empty_model_cache:
            overrides.update({
                'HF_HOME': str(isolated_home / 'hf'),
                'HF_HUB_CACHE': str(isolated_home / 'hf' / 'hub'),
                'HUGGINGFACE_HUB_CACHE': str(isolated_home / 'hf' / 'hub'),
                'SENTENCE_TRANSFORMERS_HOME': str(isolated_home / 'sentence-transformers'),
            })
        def expanduser(path):
            return str(isolated_home) if path == '~' else original_expanduser(path)

        with (
            patch.dict(os.environ, overrides),
            patch.object(os.path, 'expanduser', expanduser),
            patch.object(builtins, 'open', guarded_open),
            patch.object(Path, 'read_text', guarded_read),
            patch.object(socket.socket, 'connect', local_connect),
            patch.object(httpx.HTTPTransport, 'handle_request', local_http),
            patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', local_async_http),
        ):
            import chromadb
            import pytest

            def memory_client(*args, **kwargs):
                return chromadb.EphemeralClient(
                    settings=chromadb.Settings(anonymized_telemetry=False)
                )

            with patch.object(chromadb, 'PersistentClient', memory_client):
                import app.main  # noqa: F401  在全部隔离边界内导入应用。

                if args.verify_isolation:
                    from app.config import settings
                    from app.services.claude_client import claude_client
                    assert settings.database_url == 'sqlite:///:memory:'
                    assert settings.kb_chroma_url == ''
                    assert claude_client.client is None
                    assert Path(settings.upload_dir).is_relative_to(isolated_home)
                    for protected in protected_files:
                        try:
                            with guarded_open(protected) as stream:
                                assert stream.read() == ''
                        except FileNotFoundError:
                            pass
                    with socket.socket() as probe:
                        try:
                            probe.connect(('203.0.113.1', 443))
                        except RuntimeError:
                            pass
                        else:
                            raise AssertionError('external connection was allowed')
                    print(json.dumps({
                        'isolation': 'PASS', 'database': 'memory',
                        'chroma': 'ephemeral', 'model_client': 'unconfigured',
                        'personal_config': 'blocked', 'external_network': 'blocked',
                    }))
                    return 0
                return pytest.main(pytest_args or ['tests', '-q', '--tb=short'])

if __name__ == '__main__':
    raise SystemExit(main())
