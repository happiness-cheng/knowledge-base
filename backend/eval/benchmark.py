"""不导入应用或模型的评测契约：证据、分母、逐条观测和运行来源。"""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import re
from time import perf_counter
from typing import Callable


def _compact(value: str | None) -> str:
    return re.sub(r'\s+', '', value or '')


@dataclass(frozen=True)
class EvidenceTarget:
    node_id: int
    head: str
    tail: str | None = None

    def __post_init__(self):
        if isinstance(self.node_id, bool) or not isinstance(self.node_id, int) or self.node_id <= 0:
            raise ValueError('evidence target requires positive integer node id')
        if not isinstance(self.head, str) or not _compact(self.head):
            raise ValueError('evidence target requires nonempty head')
        if self.tail is not None and not isinstance(self.tail, str):
            raise ValueError('evidence target tail must be a string or null')


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    question: str
    gold_node_id: int | None = None
    evidence_head: str | None = None
    evidence_tail: str | None = None
    note_type: str = 'unknown'
    query_source: str = 'authored'
    gold_evidence: tuple[EvidenceTarget, ...] = ()

    def __post_init__(self):
        if not self.case_id.strip() or not self.question.strip():
            raise ValueError('case id and question must be nonempty')
        if self.gold_node_id is not None and (
            isinstance(self.gold_node_id, bool) or not isinstance(self.gold_node_id, int)
            or self.gold_node_id <= 0 or not self.evidence_head
        ):
            raise ValueError('positive case requires node id and evidence')
        if self.gold_evidence and any(value is not None for value in (
            self.gold_node_id, self.evidence_head, self.evidence_tail,
        )):
            raise ValueError('cannot mix gold_evidence with legacy gold fields')
        # 复制为不可变记录；重复锚点不能增加分母，同文档的不同区间分别计数。
        targets = {}
        for value in self.gold_evidence:
            target = value if isinstance(value, EvidenceTarget) else EvidenceTarget(**value)
            key = (target.node_id, _compact(target.head), _compact(target.tail))
            targets.setdefault(key, target)
        object.__setattr__(self, 'gold_evidence', tuple(targets.values()))


@dataclass
class BenchmarkObservation:
    retrieved: list[dict] = field(default_factory=list)
    answer: str = ''
    citations: list[int] = field(default_factory=list)
    refused: bool = False
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    steps: list[dict] = field(default_factory=list)


def load_cases(path: Path) -> list[BenchmarkCase]:
    raw = json.loads(path.read_text(encoding='utf-8'))
    rows = raw['cases'] if isinstance(raw, dict) else raw
    cases = []
    for row in rows:
        if isinstance(row, list):
            cid, nid, layer, source, question, head, tail = row
            case = BenchmarkCase(cid, question, nid, head, tail, layer, source)
        else:
            case = BenchmarkCase(**row)
        cases.append(case)
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError('duplicate case id')
    return cases


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _evidence_present(content: str, head: str | None, tail: str | None) -> bool:
    # 同一块中有完整有序锚点才算证据覆盖，不能仅凭父文档 id 命中。
    text, head, tail = _compact(content), _compact(head), _compact(tail)
    start = text.find(head)
    return bool(head) and start >= 0 and (not tail or text.find(tail, start) >= 0)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 3)


def _summary(rows: list[dict], *, answer_evaluated: bool = True) -> dict:
    valid = [row for row in rows if row['status'] != 'invalid_gold']
    positive = [row for row in valid if row['answerable']]
    negative = [row for row in valid if not row['answerable']]
    mean = lambda items, name: sum(row.get(name, 0) for row in items) / len(items) if items else None
    latencies = [row['latency_ms'] for row in valid if row.get('latency_ms') is not None]
    def tokens(name):
        # 任一有效用例未记录用量时，不输出误导性的总 token=0。
        return sum(row[name] for row in valid) if valid and all(row.get(name) is not None for row in valid) else None
    evidence_covered = sum(row['evidence_covered'] for row in positive)
    evidence_targets = sum(row['evidence_targets'] for row in positive)
    return {
        'total_cases': len(rows), 'valid_cases': len(valid),
        'invalid_cases': len(rows) - len(valid),
        'execution_errors': sum(row['status'] == 'execution_error' for row in valid),
        'positive_cases': len(positive), 'negative_cases': len(negative),
        'hit_at_1': mean(positive, 'hit_at_1'), 'hit_at_3': mean(positive, 'hit_at_3'),
        'mrr': mean(positive, 'reciprocal_rank'),
        'evidence_in_context': mean(positive, 'evidence_in_context'),
        'document_recall_at_1': mean(positive, 'document_recall_at_1'),
        'document_recall_at_3': mean(positive, 'document_recall_at_3'),
        'document_recalled_at_1': sum(row['document_recalled_at_1'] for row in positive),
        'document_recalled_at_3': sum(row['document_recalled_at_3'] for row in positive),
        'document_targets': sum(row['document_targets'] for row in positive),
        'evidence_covered': evidence_covered, 'evidence_targets': evidence_targets,
        'evidence_coverage': evidence_covered / evidence_targets if evidence_targets else None,
        'evidence_all_covered': mean(positive, 'evidence_all_covered'),
        'refusal_rate': mean(negative, 'refusal_correct') if answer_evaluated else None,
        'refusal_detected_rate': mean(negative, 'refusal_detected') if answer_evaluated else None,
        'refusal_with_citations_rate': mean(negative, 'refusal_with_citations') if answer_evaluated else None,
        'citation_valid_rate': mean(valid, 'citation_valid') if answer_evaluated else None,
        'latency_p50_ms': _percentile(latencies, .5),
        'latency_p95_ms': _percentile(latencies, .95),
        'total_input_tokens': tokens('input_tokens'), 'total_output_tokens': tokens('output_tokens'),
        'usage_status': 'complete' if valid and all(row.get('usage_status') == 'complete' for row in valid) else 'unknown',
    }


def evaluate(
    cases: list[BenchmarkCase], corpus: dict[int, str],
    executor: Callable[[BenchmarkCase], BenchmarkObservation], metadata: dict,
) -> dict:
    rows = []
    for case in cases:
        targets = [asdict(target) for target in case.gold_evidence]
        if case.gold_node_id is not None:
            targets = [{'node_id': case.gold_node_id, 'head': case.evidence_head, 'tail': case.evidence_tail}]
        gold_ids = list(dict.fromkeys(target['node_id'] for target in targets))
        row = {'case_id': case.case_id, 'question': case.question,
               'note_type': case.note_type, 'query_source': case.query_source,
               'answerable': bool(targets), 'status': 'ok',
               'gold_mode': 'multi_evidence' if case.gold_evidence else 'legacy_single' if targets else 'negative',
               'gold_evidence': targets, 'gold_document_ids': gold_ids,
               'hit_at_1': 0, 'hit_at_3': 0, 'reciprocal_rank': 0.,
               'evidence_in_context': 0, 'refusal_correct': 0, 'citation_valid': False,
               'refusal_detected': 0, 'refusal_with_citations': 0, 'review_required': False,
               'document_recalled_at_1': 0, 'document_recalled_at_3': 0,
               'document_targets': len(gold_ids),
               'document_recall_at_1': 0. if targets else None,
               'document_recall_at_3': 0. if targets else None,
               'evidence_covered': 0, 'evidence_targets': len(targets),
               'evidence_coverage': 0. if targets else None,
               'evidence_all_covered': 0 if targets else None, 'usage_status': 'unknown'}
        invalid_targets = [target for target in targets if (
            target['node_id'] not in corpus or not _evidence_present(
                corpus[target['node_id']], target['head'], target['tail'])
        )]
        if invalid_targets:
            row.update(status='invalid_gold', error='missing_node_or_evidence', invalid_gold_targets=invalid_targets)
            rows.append(row)
            continue
        started = perf_counter()
        try:
            observation = executor(case)
            row.update(asdict(observation))
            if observation.latency_ms is None:
                row['latency_ms'] = (perf_counter() - started) * 1000
            ordered_ids = list(dict.fromkeys(item['node_id'] for item in observation.retrieved))
            # 保留单 gold 的原口径；多 gold 的 Hit/MRR 只衡量任一必需文档的首次命中。
            rank = next((index + 1 for index, node_id in enumerate(ordered_ids) if node_id in gold_ids), None)
            citations_ok = set(observation.citations) <= (set(ordered_ids) & set(corpus))
            recalled_at_1 = len(set(gold_ids) & set(ordered_ids[:1]))
            recalled_at_3 = len(set(gold_ids) & set(ordered_ids[:3]))
            covered = sum(any(
                item['node_id'] == target['node_id'] and _evidence_present(
                    item.get('content', ''), target['head'], target['tail'])
                for item in observation.retrieved
            ) for target in targets)
            all_covered = int(bool(targets) and covered == len(targets))
            row.update(
                rank=rank, hit_at_1=int(rank == 1), hit_at_3=int(rank is not None and rank <= 3),
                reciprocal_rank=1 / rank if rank else 0., citation_valid=citations_ok,
                evidence_in_context=all_covered,
                document_recalled_at_1=recalled_at_1, document_recalled_at_3=recalled_at_3,
                document_recall_at_1=recalled_at_1 / len(gold_ids) if gold_ids else None,
                document_recall_at_3=recalled_at_3 / len(gold_ids) if gold_ids else None,
                evidence_covered=covered, evidence_coverage=covered / len(targets) if targets else None,
                evidence_all_covered=all_covered if targets else None,
                usage_status='complete' if observation.input_tokens is not None and observation.output_tokens is not None else 'unknown',
                refusal_correct=int(observation.refused and not observation.citations and citations_ok),
                refusal_detected=int(observation.refused),
                refusal_with_citations=int(observation.refused and bool(observation.citations)),
                review_required=bool(observation.refused and observation.citations),
            )
        except Exception as exc:
            row.update(status='execution_error', error=type(exc).__name__,
                       latency_ms=(perf_counter() - started) * 1000)
        rows.append(row)
    layers = {}
    answer_evaluated = metadata.get('mode') != 'retrieval'
    for field_name in ('note_type', 'query_source'):
        for value in sorted({row[field_name] for row in rows}):
            layers[f'{field_name}:{value}'] = _summary([row for row in rows if row[field_name] == value], answer_evaluated=answer_evaluated)
    return {'schema_version': 2, 'metadata': metadata, 'summary': _summary(rows, answer_evaluated=answer_evaluated),
            'layers': layers, 'cases': rows,
            'metric_definitions': {
                'hit_at_1': '有效正例的任一必需文档出现在首个去重文档；单 gold 保留原口径',
                'hit_at_3': '有效正例的任一必需文档出现在前 3 个去重文档；不等于多文档 Recall',
                'mrr': '有效正例中首个必需文档的倒数排名均值；单 gold 保留原口径',
                'document_recall_at_1': '逐题前 1 个去重文档召回的必需文档数 / 必需文档总数，再对有效正例取均值（macro）',
                'document_recall_at_3': '逐题前 3 个去重文档召回的必需文档数 / 必需文档总数，再对有效正例取均值（macro）',
                'document_recalled_at_1': '有效正例前 1 文档的召回数总和；与 document_targets 构成 micro 分子/分母',
                'document_recalled_at_3': '有效正例前 3 文档的召回数总和；与 document_targets 构成 micro 分子/分母',
                'evidence_coverage': '实际 retrieved 内容中覆盖的唯一证据区间数 / 有效正例唯一证据区间总数（micro）',
                'evidence_all_covered': '所有必需证据区间均覆盖的有效正例比例；evidence_in_context 的兼容别名',
                'denominators': 'invalid_gold 整题排除且不执行；execution_error 保留在有效正负例和证据/文档分母中',
            },
            'limitations': ['机械证据与引用检查不等于答案正确性；需人工复核',
                            '负例 refused 来自执行器的显式判定，报告必须注明其规则',
                            'refusal_rate 保留旧严格无引用条件；detected / with_citations 分开观察，不等于人工语义正确率',
                            '多证据为全部必需；文档 Recall 与证据覆盖分开统计，未召回证据不能从 gold 正文补入',
                            '文档排名沿用去重父文档口径；不代表原始向量块的 Recall@K',
                            '用量缺失为 unknown / null；离线桩结果不代表模型或真实检索质量']}


def render_markdown(report: dict) -> str:
    lines = ['# Knowledge benchmark', '', '```json',
             json.dumps(report['metadata'], ensure_ascii=False, indent=2), '```', '',
             '| 指标 | 结果 |', '|---|---|']
    lines.extend(f'| {key} | {value} |' for key, value in report['summary'].items())
    lines += ['', '| case | status | rank | evidence | citations | docs@1 | docs@3 | evidence spans | all covered |',
              '|---|---|---|---|---|---|---|---|---|']
    lines.extend(
        f"| {row['case_id']} | {row['status']} | {row.get('rank')} | {row['evidence_in_context']} | {row['citation_valid']} | "
        f"{row.get('document_recall_at_1')} | {row.get('document_recall_at_3')} | "
        f"{row.get('evidence_covered', '?')}/{row.get('evidence_targets', '?')} | {row.get('evidence_all_covered')} |"
        for row in report['cases']
    )
    if report.get('metric_definitions'):
        lines += ['', '| 指标口径 | 定义 |', '|---|---|']
        lines.extend(f'| {key} | {value} |' for key, value in report['metric_definitions'].items())
    lines += ['', *report['limitations'], '']
    return '\n'.join(lines)
