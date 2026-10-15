"""公开演示读取冻结答案并限制检索证据范围。"""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from eval.public_demo import PublicDemo


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.doc = dict(node_id=101, title='公开文档', content='公开正文',
                        source_url='https://docs.python.org/3.14/reference/expressions.html',
                        source_section='6.2.10', source_version='3.14', checked_at='2026-10-12',
                        content_kind='editorial_summary')
        self.chunk = {'id': '101:0', 'document': '公开正文', 'metadata': dict(self.doc, heading='原理')}
        self.write('corpus.json', {'documents': [self.doc]})
        self.write('chunks.json', [self.chunk])
        self.write('manifest.json', {'chunks_sha256': hashlib.sha256((self.root / 'chunks.json').read_bytes()).hexdigest()})
        self.write('cases.json', [{'case_id': 'U01', 'question': '问题'}])
        self.write('observations.json', [{'case_id': 'U01', 'question': '问题',
                    'retrieved': [dict(self.chunk['metadata'], content='公开正文', distance=0.7)]}])
        self.answer = self.root / 'answers.json'
        self.write('answers.json', {'rows': [{'case_id': 'U01', 'question': '问题',
                    'result': {'answer_status': 'supported', 'content': '解释[doc:101]', 'source_ids': [101]}}]})

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value), encoding='utf-8')

    def demo(self):
        return PublicDemo(self.root, self.answer)

    def test_replay_has_explicit_origin_and_canonical_evidence(self):
        replay = self.demo().replay('U01')
        self.assertEqual(replay['mode'], 'recorded_model_answer')
        self.assertFalse(replay['live_model_call'])
        self.assertEqual(replay['evidence'][0]['content'], '公开正文')
        self.assertEqual(replay['answer']['source_ids'], [101])

    def test_unknown_case_and_document_are_not_substituted(self):
        demo = self.demo()
        with self.assertRaises(KeyError):
            demo.replay('unknown')
        with self.assertRaises(KeyError):
            demo.document(999)

    def test_tampered_chunk_fails_closed(self):
        self.write('chunks.json', [])
        with self.assertRaises(ValueError):
            self.demo()

    def test_search_returns_only_snapshot_chunks_not_recorded_answer(self):
        demo = self.demo()
        result = demo.search('任意问题', lambda _: {'ids': [['101:0']], 'distances': [[0.8]]})
        self.assertEqual(result['mode'], 'live_local_retrieval')
        self.assertIsNone(result['answer'])
        self.assertEqual(result['evidence'][0]['node_id'], 101)
        with self.assertRaises(ValueError):
            demo.search('任意问题', lambda _: {'ids': [['private:0']], 'distances': [[0.8]]})

    def test_answer_from_another_question_is_rejected(self):
        data = json.loads(self.answer.read_text(encoding='utf-8'))
        data['rows'][0]['question'] = '另一个问题'
        self.write('answers.json', data)
        with self.assertRaises(ValueError):
            self.demo()

    def test_replay_cannot_reference_private_or_missing_documents(self):
        data = json.loads(self.answer.read_text(encoding='utf-8'))
        data['rows'][0]['result']['source_ids'] = [999]
        self.write('answers.json', data)
        with self.assertRaises(ValueError):
            self.demo()

    def test_replay_evidence_must_match_public_snapshot(self):
        self.write('observations.json', [{'case_id': 'U01', 'question': '问题',
                    'retrieved': [{'node_id': 101, 'content': '不在公开快照中的内容'}]}])
        with self.assertRaises(ValueError):
            self.demo()


if __name__ == '__main__':
    unittest.main()
