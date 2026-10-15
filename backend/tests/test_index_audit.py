"""只读索引对账通过公共接口报告差异，不能把数量相同当作内容一致。"""
import hashlib
import json
import sqlite3

import pytest

from eval.index_audit import audit_index, read_chroma_snapshot


def test_empty_configured_collection_and_missing_nodes_are_unhealthy():
    report = audit_index([{'node_id': 7, 'title': '标题', 'content': '正文'}],
                         {'name': 'user_4_nodes_prod', 'exists': True, 'dimension': None, 'chunks': []})
    assert report['health'] == 'unhealthy'
    assert report['missing_node_ids'] == [7]
    assert report['freshness']['status'] == 'unknown'
    assert report['embedding']['status'] == 'unknown'


def test_orphan_dimension_and_title_mismatch_are_reported_without_note_content():
    index = {'name': 'selected', 'exists': True, 'dimension': 384, 'chunks': [
        {'chunk_id': '7:0', 'node_id': 7, 'title': '旧标题', 'document': '旧内容 secret-value'},
        {'chunk_id': '9:0', 'node_id': 9, 'title': '孤儿', 'document': '孤儿正文'},
    ]}
    report = audit_index([{'node_id': 7, 'title': '新标题', 'content': '新内容'}], index)
    assert report['orphan_node_ids'] == [9]
    assert report['title_mismatch_chunk_ids'] == ['7:0']
    assert report['embedding']['status'] == 'mismatch'
    assert report['health'] == 'unhealthy'
    assert 'secret-value' not in json.dumps(report)
    assert report['freshness']['status'] == 'unknown'


def test_same_counts_can_hide_changed_missing_and_obsolete_chunks():
    nodes = [{'node_id': 7, 'title': '标题', 'content': '新版内容'}]
    index = {'name': 'selected', 'exists': True, 'dimension': 1024, 'chunks': [
        {'chunk_id': '7:0', 'node_id': 7, 'title': '标题', 'heading': '开头', 'document': '旧版内容'},
        {'chunk_id': '7:2', 'node_id': 7, 'title': '标题', 'heading': '多余', 'document': '旧尾部'},
    ]}
    expected = [
        {'chunk_id': '7:0', 'node_id': 7, 'title': '标题', 'heading': '开头', 'document': '新版内容'},
        {'chunk_id': '7:1', 'node_id': 7, 'title': '标题', 'heading': '尾部', 'document': '新尾部'},
    ]
    report = audit_index(nodes, index, expected_chunks=expected)
    assert report['chunk_comparison']['changed_chunk_ids'] == ['7:0']
    assert report['chunk_comparison']['missing_chunk_ids'] == ['7:1']
    assert report['chunk_comparison']['unexpected_chunk_ids'] == ['7:2']
    assert report['freshness']['status'] == 'unknown'  # 没有索引时的文档版本凭据。
    assert report['health'] == 'unhealthy'


def test_reader_is_read_only_and_missing_collection_does_not_create_one(tmp_path):
    path = tmp_path / 'chroma.sqlite3'
    db = sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE collections(id TEXT, name TEXT, dimension INTEGER, config_json_str TEXT);
        CREATE TABLE segments(id TEXT, collection TEXT, scope TEXT);
        CREATE TABLE embeddings(id INTEGER, segment_id TEXT, embedding_id TEXT);
        CREATE TABLE embedding_metadata(id INTEGER,key TEXT,string_value TEXT,int_value INTEGER);
        INSERT INTO collections VALUES ('c','selected',1024,'{}');
        INSERT INTO segments VALUES ('s','c','METADATA');
        INSERT INTO embeddings VALUES (1,'s','7:0');
        INSERT INTO embedding_metadata VALUES (1,'node_id',NULL,7);
        INSERT INTO embedding_metadata VALUES (1,'chroma:document','正文',NULL);
    ''')
    db.commit()
    db.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    index = read_chroma_snapshot(path, 'selected')
    assert index['chunks'][0]['node_id'] == 7
    assert index['chunks'][0]['document'] == '正文'
    assert not read_chroma_snapshot(path, 'absent')['exists']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(FileNotFoundError):
        read_chroma_snapshot(tmp_path/'missing.sqlite3', 'selected')
    assert not (tmp_path/'missing.sqlite3').exists()
