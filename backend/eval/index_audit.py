"""只读快照对账；不导入应用、不创建集合、不修复索引。"""

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode('utf-8')).hexdigest()


def read_chroma_snapshot(path: Path, collection_name: str) -> dict:
    """读取已存在 SQLite metadata；向量和 HNSW 是否健康需另外验证。"""
    path = path.resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        required = {
            'collections': {'id', 'name', 'dimension', 'config_json_str'},
            'segments': {'id', 'collection', 'scope'},
            'embeddings': {'id', 'segment_id', 'embedding_id'},
            'embedding_metadata': {'id', 'key', 'string_value', 'int_value'},
        }
        for table, columns in required.items():
            actual = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
            if not columns <= actual:
                raise ValueError(f'unsupported Chroma SQLite structure: {table}')
        row = db.execute('SELECT id,dimension,config_json_str FROM collections WHERE name=?',
                         (collection_name,)).fetchone()
        if row is None:
            return {'name': collection_name, 'exists': False, 'dimension': None, 'chunks': []}
        collection_id, dimension, config = row
        entries = db.execute('''SELECT e.id,e.embedding_id FROM embeddings e
            JOIN segments s ON e.segment_id=s.id WHERE s.collection=? AND s.scope='METADATA'
            ORDER BY e.id''', (collection_id,)).fetchall()
        chunks = []
        for internal_id, chunk_id in entries:
            metadata = {key: text if text is not None else number for key, text, number in
                        db.execute('SELECT key,string_value,int_value FROM embedding_metadata WHERE id=?',
                                   (internal_id,))}
            chunks.append({'chunk_id': chunk_id, 'node_id': metadata.get('node_id'),
                'title': metadata.get('title'), 'heading': metadata.get('heading'),
                'chunk_index': metadata.get('chunk_index'), 'document': metadata.get('chroma:document'),
                'source_document_hash': metadata.get('source_document_hash')})
        return {'name': collection_name, 'exists': True, 'dimension': dimension,
                'configuration': json.loads(config) if config else {}, 'chunks': chunks}


def audit_index(nodes: list[dict], index: dict, *, expected_dimension=1024,
                expected_chunks: list[dict] | None = None) -> dict:
    """数量、内容、版本凭据分别判断；数量相同不是通过条件。"""
    canonical = {node['node_id']: node for node in nodes}
    if len(canonical) != len(nodes) or any(type(nid) is not int or nid <= 0 for nid in canonical):
        raise ValueError('canonical snapshot has invalid or duplicate node IDs')
    chunks = index['chunks']
    malformed = [c['chunk_id'] for c in chunks if type(c.get('node_id')) is not int
                 or c['node_id'] <= 0 or not isinstance(c.get('document'), str)]
    indexed_ids = {c['node_id'] for c in chunks if type(c.get('node_id')) is int and c['node_id'] > 0}
    missing, orphan = sorted(set(canonical) - indexed_ids), sorted(indexed_ids - set(canonical))
    duplicate_ids = sorted(cid for cid, count in Counter(c['chunk_id'] for c in chunks).items() if count > 1)
    title_mismatch = sorted(c['chunk_id'] for c in chunks if c.get('node_id') in canonical
                            and c.get('title') != canonical[c['node_id']].get('title', ''))
    dimension = index.get('dimension')
    dimension_status = 'unknown' if dimension is None else 'match' if dimension == expected_dimension else 'mismatch'
    comparison = {'status': 'not_checked', 'changed_chunk_ids': [], 'missing_chunk_ids': [],
                  'unexpected_chunk_ids': []}
    if expected_chunks is not None:
        expected = {c['chunk_id']: c for c in expected_chunks}
        if len(expected) != len(expected_chunks) or any(c.get('node_id') not in canonical for c in expected_chunks):
            raise ValueError('expected chunks have duplicate IDs or nodes outside canonical snapshot')
        observed = {c['chunk_id']: c for c in chunks}
        comparison.update(status='compared_to_current_splitter',
            missing_chunk_ids=sorted(set(expected) - set(observed)),
            unexpected_chunk_ids=sorted(set(observed) - set(expected)),
            changed_chunk_ids=sorted(cid for cid in set(expected) & set(observed)
                if any(expected[cid].get(key) != observed[cid].get(key)
                       for key in ('node_id', 'title', 'heading', 'document'))))
    # 本项目历史块未保存索引时父文档 hash；只输出当前 hash，不能倒推当时版本。
    current_hashes = {str(nid): _hash({'title': n.get('title', ''), 'content': n['content']})
                      for nid, n in canonical.items()}
    has_hashes = bool(chunks) and all(c.get('source_document_hash') for c in chunks)
    hash_mismatch = sorted(c['chunk_id'] for c in chunks if c.get('node_id') in canonical
        and c.get('source_document_hash') and c['source_document_hash'] != current_hashes[str(c['node_id'])])
    freshness = {'status': 'mismatch' if hash_mismatch else 'match' if has_hashes and not missing and not orphan else 'unknown',
                 'mismatch_chunk_ids': hash_mismatch,
                 'hash_definition': 'sha256 of UTF-8 compact sorted JSON {title,content}'}
    errors = []
    for condition, code in [
        (not index.get('exists'), 'collection_missing'),
        (bool(canonical) and not chunks, 'collection_empty_with_saved_notes'),
        (bool(missing), 'nodes_missing_from_index'), (bool(orphan), 'orphan_index_nodes'),
        (bool(malformed), 'malformed_chunk_metadata'), (bool(duplicate_ids), 'duplicate_chunk_ids'),
        (bool(title_mismatch), 'title_mismatch'), (dimension_status == 'mismatch', 'embedding_dimension_mismatch'),
        (bool(hash_mismatch), 'source_document_hash_mismatch'),
        (any(comparison[k] for k in ('changed_chunk_ids', 'missing_chunk_ids', 'unexpected_chunk_ids')), 'chunk_content_difference'),
    ]:
        if condition:
            errors.append(code)
    return {'schema_version': 1, 'collection': index['name'], 'collection_exists': index.get('exists', False),
        'health': 'unhealthy' if errors else 'needs_verification', 'errors': errors,
        'canonical_node_count': len(nodes), 'indexed_node_count': len(indexed_ids), 'chunk_count': len(chunks),
        'missing_node_ids': missing, 'orphan_node_ids': orphan, 'malformed_chunk_ids': malformed,
        'duplicate_chunk_ids': duplicate_ids, 'title_mismatch_chunk_ids': title_mismatch,
        'chunks_per_node': {str(nid): sum(c.get('node_id') == nid for c in chunks) for nid in sorted(indexed_ids)},
        'embedding': {'expected_dimension': expected_dimension, 'stored_dimension': dimension,
                      'status': dimension_status, 'model_identity': 'unknown', 'normalization': 'unknown'},
        'configuration': index.get('configuration', {}), 'freshness': freshness,
        'chunk_comparison': comparison, 'current_document_hashes': current_hashes,
        'chunk_hashes': {c['chunk_id']: _hash(c.get('document')) for c in chunks},
        'limitations': ['metadata snapshot does not verify ANN files or embedding values',
            'matching dimensions does not prove model identity or normalization',
            'current splitter differences do not alone prove historical index staleness',
            'no repair, migration, collection creation, model calls or note text output']}


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--chroma-sqlite', required=True, type=Path)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--expected-chunks', type=Path)
    parser.add_argument('--expected-dimension', type=int, default=1024)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.expected_dimension < 1:
        parser.error('expected dimension must be positive')
    # 禁止将诊断报告覆盖到任何输入；输出也不覆盖已有报告。
    inputs = [args.corpus, args.chroma_sqlite] + ([args.expected_chunks] if args.expected_chunks else [])
    if args.output.resolve() in {path.resolve() for path in inputs}:
        parser.error('output must not overwrite input')
    if args.output.exists():
        parser.error('output already exists; choose a new report path')
    try:
        nodes = json.loads(args.corpus.read_text(encoding='utf-8'))['nodes']
        expected = json.loads(args.expected_chunks.read_text(encoding='utf-8'))['chunks'] if args.expected_chunks else None
        report = audit_index(nodes, read_chroma_snapshot(args.chroma_sqlite, args.collection),
                             expected_dimension=args.expected_dimension, expected_chunks=expected)
        report['measured_at'] = datetime.now(timezone.utc).isoformat()
        report['input_hashes'] = {path.name: sha256(path.read_bytes()).hexdigest() for path in inputs}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({'health': report['health'], 'errors': report['errors'], 'report': str(args.output)}, ensure_ascii=False))
        return 2 if report['health'] == 'unhealthy' else 0
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        print(json.dumps({'status': 'audit_failed', 'error_type': type(exc).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
