"""隔离公开语料演示：答案回放与实时检索明确分开。"""
from hashlib import sha256
import json

from eval.public_corpus import load_documents


class PublicDemo:
    def __init__(self, corpus_run, answer_report):
        def read(name):
            return json.loads((corpus_run / name).read_text(encoding='utf-8'))
        self.documents = {d['node_id']: d for d in load_documents(read('corpus.json')['documents'])}
        manifest = read('manifest.json')
        if sha256((corpus_run / 'chunks.json').read_bytes()).hexdigest() != manifest['chunks_sha256']:
            raise ValueError('public chunk snapshot hash mismatch')
        self.chunks = {c['id']: c for c in read('chunks.json')}
        self.cases = {c['case_id']: c for c in read('cases.json')}
        self.observations = {o['case_id']: o for o in read('observations.json')}
        self.answers = {r['case_id']: r for r in json.loads(answer_report.read_text(encoding='utf-8'))['rows']}
        self.corpus_run = corpus_run.name
        self.answer_run = answer_report.parent.name
        for case_id, row in self.answers.items():
            if case_id not in self.cases or row['question'] != self.cases[case_id]['question']:
                raise ValueError('answer question mismatch')
            observation = self.observations[case_id]
            for evidence in observation['retrieved']:
                if not any(c['metadata']['node_id'] == evidence['node_id'] and c['document'] == evidence['content']
                           for c in self.chunks.values()):
                    raise ValueError('replay evidence outside public snapshot')
            allowed = {e['node_id'] for e in observation['retrieved']}
            if not set(row['result']['source_ids']) <= allowed:
                raise ValueError('answer citation outside replay evidence')

    def catalog(self):
        return {'documents': list(self.documents.values()),
                'cases': [{'case_id': c['case_id'], 'question': c['question']} for c in self.cases.values()],
                'corpus_run': self.corpus_run, 'answer_run': self.answer_run,
                'model_api_enabled': False, 'content_kind': 'editorial_summary'}

    def document(self, node_id):
        return self.documents[node_id]

    def replay(self, case_id):
        row = self.answers[case_id]
        return {'mode': 'recorded_model_answer', 'live_model_call': False, 'case_id': case_id,
                'question': row['question'], 'answer': row['result'],
                'evidence': self.observations[case_id]['retrieved'],
                'review_note': '开头的“核心是分布式计算”是额外概括，人工标记为需收紧。' if case_id == 'U01' else None}

    def search(self, question, query_index):
        results = query_index(question)
        counts, order, grouped = {}, [], {}
        for chunk_id, distance in zip(results['ids'][0], results['distances'][0], strict=True):
            if chunk_id not in self.chunks:
                raise ValueError('index result outside public snapshot')
            chunk = self.chunks[chunk_id]
            meta = chunk['metadata']
            node_id = meta['node_id']
            if node_id not in grouped:
                grouped[node_id] = []
                order.append(node_id)
            if counts.get(node_id, 0) < 2:
                grouped[node_id].append(dict(meta, content=chunk['document'], distance=distance))
                counts[node_id] = counts.get(node_id, 0) + 1
        return {'mode': 'live_local_retrieval', 'live_model_call': False, 'question': question,
                'answer': None, 'evidence': [c for nid in order[:3] for c in grouped[nid]]}
