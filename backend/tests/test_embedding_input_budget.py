from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import chromadb
import pytest

from app.services import rag_service
from app.services.embedding_input import prepare_chunks


class CharacterTokenizer:
    def __call__(self, text, *, add_special_tokens=True, **kwargs):
        return {'input_ids': list(range(len(text) + (2 if add_special_tokens else 0)))}


def test_complete_embedding_headers_and_body_fit_model_without_losing_body():
    original = '知' * 480
    chunks = prepare_chunks([('小节', original)], '标' * 80, CharacterTokenizer())
    assert len(chunks) >= 2
    assert ''.join(chunk.content for chunk in chunks) == original
    assert all(chunk.token_count <= 512 for chunk in chunks)
    assert all('标' * 80 in chunk.embedding_text for chunk in chunks)


def test_extremely_long_headers_are_shortened_only_for_embedding():
    title, heading, body = '标题' * 500, '小节' * 200, '正文' * 250
    chunks = prepare_chunks([(heading, body)], title, CharacterTokenizer())
    assert ''.join(chunk.content for chunk in chunks) == body
    assert all(chunk.heading == heading for chunk in chunks)
    assert all(chunk.header_shortened and chunk.token_count <= 512 for chunk in chunks)


def test_short_complete_input_remains_unchanged():
    chunks = prepare_chunks([('head', 'body')], 'title', CharacterTokenizer())
    assert len(chunks) == 1
    assert chunks[0].embedding_text == 'title\nhead\nbody'
    assert not chunks[0].header_shortened


def test_native_encoder_rejects_long_query_before_silent_truncation(monkeypatch):
    model = SimpleNamespace(tokenizer=CharacterTokenizer(), max_seq_length=512, encode=Mock())
    monkeypatch.setattr(rag_service, '_get_model', lambda: model)
    with pytest.raises(ValueError, match='embedding.*budget'):
        rag_service.get_query_embedding('查' * 600)
    model.encode.assert_not_called()


def test_missing_tokenizer_is_explicit_error_instead_of_character_estimate():
    with pytest.raises(ValueError, match='tokenizer'):
        prepare_chunks([('head', 'body')], 'title', None)


def test_empty_content_needs_no_tokenizer():
    assert prepare_chunks([], 'title', None) == []


def test_actual_index_prepares_full_input_before_upsert(monkeypatch):
    tokenizer = CharacterTokenizer()
    client = chromadb.EphemeralClient(settings=chromadb.Settings(anonymized_telemetry=False))
    monkeypatch.setattr(rag_service, 'chroma_client', client)
    monkeypatch.setattr(rag_service, '_SUFFIX', f'_budget_{uuid4().hex}')
    monkeypatch.setattr(rag_service, 'split_by_headings', lambda content: [('小节', content)])
    monkeypatch.setattr(rag_service, '_get_tokenizer', lambda: tokenizer, raising=False)
    measured = []
    def encode(text):
        measured.append(len(tokenizer(text)['input_ids']))
        return [1.0, 0.0]
    monkeypatch.setattr(rag_service, 'get_embedding', encode)
    body = '知' * 480
    rag_service.add_node_to_index(42, body, '标' * 80, user_id=1)
    assert measured and max(measured) <= 512
    rows = rag_service._get_user_collection(1).get()
    assert ''.join(rows['documents']) == body


def test_concurrent_first_queries_load_only_one_embedding_model(monkeypatch):
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from time import sleep
    from types import ModuleType

    calls = []
    module = ModuleType('sentence_transformers')
    def build(*args, **kwargs):
        calls.append(1)
        sleep(0.03)
        return object()
    module.SentenceTransformer = build
    monkeypatch.setitem(sys.modules, 'sentence_transformers', module)
    monkeypatch.setattr(rag_service, '_embedding_model', None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: rag_service._get_model(), range(4)))
    assert len(calls) == 1
    assert len({id(result) for result in results}) == 1
