"""原生回答验收入口的离线边界：默认不读取凭据、严格限制新预算。"""
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from eval.run_native_rag_validation import authorize_online, local_index, run


def test_native_profile_is_pure_plan_from_any_cwd(tmp_path):
    import eval.run_native_rag_validation as module
    result = subprocess.run([sys.executable, '-X', 'utf8', module.__file__], cwd=tmp_path,
                            capture_output=True, text=True, encoding='utf-8', check=False)
    assert result.returncode == 0
    profile = json.loads(result.stdout)
    assert [case['case_id'] for case in profile['cases']] == ['CR02', 'CR07', 'CR13', 'CR19', 'CR26']
    assert profile['blind_test'] is False and profile['semantic_accuracy'] is None
    assert profile['physical_request_limit'] == 5 and profile['physical_requests'] == 0
    assert profile['model'] == 'deepseek-flash'
    code = ('import sys; from eval.run_native_rag_validation import build_profile; build_profile(); '
            'assert not any(x=="app" or x.startswith("app.") for x in sys.modules)')
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)
    assert result.returncode == 0


@pytest.mark.parametrize('budget', [None, False, 0, 6])
def test_invalid_budget_cannot_authorize_an_online_run(budget):
    with pytest.raises((ValueError, PermissionError)):
        authorize_online(True, budget)


def test_budget_alone_does_not_authorize_external_transfer():
    with pytest.raises(PermissionError):
        authorize_online(False, 5)


def test_online_refuses_before_touching_credentials_or_models(tmp_path):
    with pytest.raises(PermissionError):
        run(model_path=tmp_path / 'missing-model', hf_home=tmp_path / 'missing-cache',
            output=tmp_path / 'report.json', online='not-a-boolean', budget=5,
            credentials_file=Path('/must-not-read.env'))
    assert not (tmp_path / 'report.json').exists()


def test_existing_report_is_preserved_before_loading_models(tmp_path):
    output = tmp_path / 'frozen-report.json'
    original = b'{"original":"evidence"}\n'
    output.write_bytes(original)
    with pytest.raises(FileExistsError):
        run(model_path=tmp_path / 'missing-model', hf_home=tmp_path / 'missing-cache', output=output)
    assert output.read_bytes() == original


def test_local_fixture_stops_listening_after_exit(tmp_path, monkeypatch):
    monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'False')
    monkeypatch.setenv('HF_HUB_OFFLINE', '1')
    with local_index(tmp_path) as client:
        port = client.get_settings().chroma_server_http_port
        collection = client.create_collection('lifecycle_probe')
        collection.upsert(ids=['one'], documents=['synthetic'], embeddings=[[1.0, 0.0]])
        assert collection.get(include=['embeddings'])['ids'] == ['one']
    with socket.socket() as probe:
        probe.settimeout(.2)
        assert probe.connect_ex(('127.0.0.1', port)) != 0
