"""显式读取冻结技术语料与题集；仅用标准库，不加载应用、模型或数据库。"""

import json
import re
from datetime import date
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath

from eval.benchmark import BenchmarkCase, load_cases


def _compact(value: str | None) -> str:
    return re.sub(r'\s+', '', value or '')


def load_manifest_corpus(manifest_path: Path, repository_root: Path) -> dict[int, str]:
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported corpus manifest schema')
    date.fromisoformat(manifest['frozen_at'])
    documents = manifest.get('documents')
    if not isinstance(documents, list) or not documents:
        raise ValueError('corpus manifest requires documents')
    root = Path(repository_root).resolve()
    allowed = (root / 'backend/eval/corpus/external').resolve()
    if not allowed.is_relative_to(root):
        raise ValueError('source path escapes repository through corpus directory')
    corpus = {}
    paths = set()
    for document in documents:
        node_id = document.get('node_id')
        if isinstance(node_id, bool) or not isinstance(node_id, int) or node_id <= 0:
            raise ValueError('manifest node id must be a positive integer')
        if node_id in corpus:
            raise ValueError('duplicate manifest node id')
        source_path = document.get('source_path')
        if not isinstance(source_path, str) or not source_path or '\\' in source_path:
            raise ValueError('source path must be a repository-relative POSIX path')
        relative = PurePosixPath(source_path)
        if (relative.is_absolute() or PureWindowsPath(source_path).drive
                or any(part in ('.', '..') for part in source_path.split('/'))
                or relative.suffix != '.md'):
            raise ValueError('source path must remain inside the technical corpus')
        source = (root / relative).resolve()
        if not source.is_relative_to(allowed):
            raise ValueError('source path must remain inside the technical corpus')
        if source in paths:
            raise ValueError('duplicate manifest source path')
        digest = document.get('source_sha256')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('source sha256 must be 64 lowercase hexadecimal characters')
        if not source.is_file():
            raise ValueError(f'missing source for node {node_id}')
        raw = source.read_bytes()
        if sha256(raw).hexdigest() != digest:
            raise ValueError(f'source hash mismatch for node {node_id}')
        corpus[node_id] = raw.decode('utf-8')
        paths.add(source)
    return corpus


def validate_core_dataset(dataset_path: Path, corpus: dict[int, str]) -> list[BenchmarkCase]:
    dataset_path = Path(dataset_path)
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    if dataset.get('schema_version') != 1:
        raise ValueError('unsupported core dataset schema')
    metadata = dataset.get('metadata', {})
    date.fromisoformat(metadata['frozen_at'])
    if metadata.get('blind_test') is not False:
        raise ValueError('source-aware authored dataset cannot claim independent blind test')
    cases = load_cases(dataset_path)
    case_metadata = dataset.get('case_metadata', {})
    if set(case_metadata) != {case.case_id for case in cases}:
        raise ValueError('case metadata must exactly cover all case ids')
    groups = {}
    for case in cases:
        details = case_metadata[case.case_id]
        if details.get('split') not in ('development', 'heldout'):
            raise ValueError(f'invalid split for {case.case_id}')
        for name in ('topic', 'template_group', 'query_category'):
            if not isinstance(details.get(name), str) or not details[name].strip():
                raise ValueError(f'case metadata requires {name} for {case.case_id}')
        group = details['template_group']
        if group in groups and groups[group] != details['split']:
            raise ValueError(f'template group crosses split: {group}')
        groups[group] = details['split']
        if case.query_source not in ('agent_simulated', 'userprovided'):
            raise ValueError(f'query source must declare provenance for {case.case_id}')
        targets = [(target.node_id, target.head, target.tail) for target in case.gold_evidence]
        if case.gold_node_id is not None:
            targets = [(case.gold_node_id, case.evidence_head, case.evidence_tail)]
        ranges = details.get('evidence_ranges')
        if not isinstance(ranges, list) or len(ranges) != len(targets):
            raise ValueError(f'evidence ranges must describe each gold target for {case.case_id}')
        if not targets and details.get('coverage_status') not in ('missing_coverage', 'ambiguous_query'):
            raise ValueError(f'negative case requires explicit missing coverage for {case.case_id}')
        for node_id, head, tail in targets:
            content = _compact(corpus.get(node_id, ''))
            anchor, end = _compact(head), _compact(tail)
            start = content.find(anchor)
            if node_id not in corpus or not anchor or start < 0 or (end and content.find(end, start) < 0):
                raise ValueError(f'invalid gold for {case.case_id}, node {node_id}')
    return cases
