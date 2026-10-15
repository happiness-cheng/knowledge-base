"""冻结技术语料必须显式加载，拒绝漂移、越界和无效 gold。"""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest


def _manifest(tmp_path, *, source_path='backend/eval/corpus/external/note.md', digest=None):
    root = tmp_path / 'repository'
    source = root / 'backend/eval/corpus/external/note.md'
    source.parent.mkdir(parents=True)
    source.write_text('开始 证据甲 结束', encoding='utf-8')
    document = {'node_id': 1001, 'source_path': source_path,
                'source_sha256': digest or sha256(source.read_bytes()).hexdigest(),
                'title': '技术笔记', 'topic': 'operating_system'}
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'frozen_at': '2026-10-13',
                                    'documents': [document]}), encoding='utf-8')
    return manifest, root, source


def test_manifest_explicitly_loads_frozen_original_text_without_application(tmp_path):
    from eval.core_corpus import load_manifest_corpus

    manifest, root, _ = _manifest(tmp_path)
    assert load_manifest_corpus(manifest, root) == {1001: '开始 证据甲 结束'}
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-c',
        ('import sys; from eval.core_corpus import load_manifest_corpus; '
        'assert not any(name == "app" or name.startswith("app.") for name in sys.modules); '
        'assert "chromadb" not in sys.modules; print("pure import")')],
        cwd=backend, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'pure import'


def test_manifest_rejects_changed_source_hash(tmp_path):
    from eval.core_corpus import load_manifest_corpus

    manifest, root, source = _manifest(tmp_path)
    source.write_text('原文改变', encoding='utf-8')
    with pytest.raises(ValueError, match='hash mismatch'):
        load_manifest_corpus(manifest, root)


def test_manifest_rejects_missing_source_without_reading_other_locations(tmp_path):
    from eval.core_corpus import load_manifest_corpus

    manifest, root, _ = _manifest(tmp_path, source_path='backend/eval/corpus/external/missing.md')
    with pytest.raises(ValueError, match='missing source'):
        load_manifest_corpus(manifest, root)


@pytest.mark.parametrize('source_path', [
    '../outside.md', 'backend/eval/corpus/external/../../../../outside.md',
    'backend/.env', 'backend/eval/corpus/external/note.txt',
])
def test_manifest_rejects_path_escape_and_non_corpus_files(tmp_path, source_path):
    from eval.core_corpus import load_manifest_corpus

    manifest, root, _ = _manifest(tmp_path, source_path=source_path)
    with pytest.raises(ValueError, match='source path'):
        load_manifest_corpus(manifest, root)


def test_manifest_rejects_absolute_path_duplicate_ids_and_malformed_hash(tmp_path):
    from eval.core_corpus import load_manifest_corpus

    manifest, root, source = _manifest(tmp_path)
    raw = json.loads(manifest.read_text(encoding='utf-8'))
    raw['documents'][0]['source_path'] = str(source.resolve())
    manifest.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='source path'):
        load_manifest_corpus(manifest, root)
    raw['documents'][0]['source_path'] = 'backend/eval/corpus/external/note.md'
    raw['documents'].append(dict(raw['documents'][0]))
    manifest.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        load_manifest_corpus(manifest, root)
    raw['documents'].pop()
    raw['documents'][0]['source_sha256'] = 'not-a-hash'
    manifest.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='sha256'):
        load_manifest_corpus(manifest, root)


def _dataset(tmp_path, *, head='证据甲', node_id=1001, split='development'):
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps({
        'schema_version': 1, 'metadata': {'frozen_at': '2026-10-13', 'blind_test': False},
        'cases': [{'case_id': 'Q01', 'question': '问题', 'gold_evidence': [
            {'node_id': node_id, 'head': head, 'tail': '结束'},
        ], 'query_source': 'agent_simulated'}],
        'case_metadata': {'Q01': {'topic': 'operating_system', 'template_group': 'scheduling',
                                  'split': split, 'query_category': 'semantic_rephrase',
                                  'evidence_ranges': ['说明段落']}},
    }, ensure_ascii=False), encoding='utf-8')
    return path


def test_dataset_loads_multigold_and_validates_all_ordered_anchors(tmp_path):
    from eval.core_corpus import validate_core_dataset

    cases = validate_core_dataset(_dataset(tmp_path), {1001: '开始 证据甲 结束'})
    assert cases[0].gold_evidence[0].node_id == 1001
    assert cases[0].query_source == 'agent_simulated'


@pytest.mark.parametrize('corpus', [{}, {1001: '错误内容'}, {1001: '结束 证据甲'}])
def test_dataset_rejects_any_gold_missing_from_frozen_source(tmp_path, corpus):
    from eval.core_corpus import validate_core_dataset

    with pytest.raises(ValueError, match='invalid gold'):
        validate_core_dataset(_dataset(tmp_path), corpus)


def test_dataset_rejects_template_group_leakage_and_missing_case_metadata(tmp_path):
    from eval.core_corpus import validate_core_dataset

    path = _dataset(tmp_path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['cases'].append({'case_id': 'Q02', 'question': '另一个问题',
                         'query_source': 'agent_simulated'})
    raw['case_metadata']['Q02'] = {**raw['case_metadata']['Q01'], 'split': 'heldout',
                                   'evidence_ranges': [], 'coverage_status': 'missing_coverage'}
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='template group'):
        validate_core_dataset(path, {1001: '证据甲 结束'})
    del raw['case_metadata']['Q02']
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='case metadata'):
        validate_core_dataset(path, {1001: '证据甲 结束'})


def test_dataset_rejects_invalid_split_and_unmarked_negative_coverage(tmp_path):
    from eval.core_corpus import validate_core_dataset

    with pytest.raises(ValueError, match='split'):
        validate_core_dataset(_dataset(tmp_path, split='random'), {1001: '证据甲 结束'})
    path = _dataset(tmp_path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['cases'][0].pop('gold_evidence')
    raw['case_metadata']['Q01']['evidence_ranges'] = []
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError, match='coverage'):
        validate_core_dataset(path, {})


def test_frozen_core_fixtures_cover_36_cases_16_files_and_all_gold_intervals():
    from collections import Counter

    from eval.core_corpus import load_manifest_corpus, validate_core_dataset

    root = Path(__file__).resolve().parents[2]
    fixtures = root / 'backend/eval/fixtures'
    manifest = fixtures / 'core-rag-corpus-20261013.json'
    dataset = fixtures / 'core-rag-20261013.json'
    corpus = load_manifest_corpus(manifest, root)
    cases = validate_core_dataset(dataset, corpus)
    raw = json.loads(dataset.read_text(encoding='utf-8'))
    assert len(corpus) == 16
    assert len(cases) == 36
    assert sum(bool(case.gold_evidence) for case in cases) == 27
    assert raw['metadata']['corpus_manifest_sha256'] == sha256(manifest.read_bytes()).hexdigest()
    assert raw['metadata']['frozen_at'] == '2026-10-13'
    assert raw['metadata']['blind_test'] is False
    assert all(case.query_source == 'agent_simulated' for case in cases)
    assert Counter(item['query_category'] for item in raw['case_metadata'].values()) == {
        'concrete_api_error': 6, 'semantic_rephrase': 6, 'multi_document': 6,
        'confusable_concepts': 6, 'missing_evidence': 6, 'typo_pronoun': 6,
    }
    assert Counter(item['split'] for item in raw['case_metadata'].values()) == {
        'development': 17, 'heldout': 19,
    }
