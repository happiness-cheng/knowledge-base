"""公开语料的来源、预算和独立目录边界。"""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from eval.public_corpus import load_documents, prepare_chunks, reserve_output


class PublicCorpusTests(unittest.TestCase):
    def setUp(self):
        self.doc = {'node_id': 101, 'title': 'Python', 'content': '## yield\n暂停并保留状态',
                    'source_url': 'https://docs.python.org/3.14/reference/expressions.html',
                    'source_section': '6.2.10', 'source_version': 'Python 3.14',
                    'checked_at': '2026-10-12', 'content_kind': 'editorial_summary'}

    def test_requires_sources_and_unique_ids(self):
        for field in ('source_url', 'source_section', 'source_version', 'checked_at', 'content'):
            doc = deepcopy(self.doc)
            doc[field] = ''
            with self.assertRaises(ValueError):
                load_documents([doc])
        with self.assertRaises(ValueError):
            load_documents([self.doc, self.doc])

    def test_rejects_nonpublic_url_and_bool_id(self):
        for field, value in [('source_url', 'file:///private'), ('node_id', True)]:
            doc = dict(self.doc, **{field: value})
            with self.assertRaises(ValueError):
                load_documents([doc])

    def test_hash_and_chunk_provenance_are_stable(self):
        documents = load_documents([self.doc])
        def split(_):
            return [('yield', '暂停并保留状态')]
        first = prepare_chunks(documents, split, len, 100)
        self.assertEqual(first, prepare_chunks(documents, split, len, 100))
        self.assertEqual(first[0]['metadata']['source_url'], self.doc['source_url'])
        self.assertEqual(len(first[0]['metadata']['content_sha256']), 64)
        changed = load_documents([dict(self.doc, content='修改')])
        self.assertNotEqual(documents[0]['content_sha256'], changed[0]['content_sha256'])

    def test_budget_includes_title_heading_and_special_tokens(self):
        with self.assertRaises(ValueError):
            prepare_chunks(load_documents([self.doc]), lambda _: [('yield', '正文')],
                           lambda text: len(text) + 2, 10)

    def test_empty_chunk_is_rejected(self):
        for chunks in ([], [('empty', '')]):
            with self.assertRaises(ValueError):
                prepare_chunks(load_documents([self.doc]), lambda _: chunks, len, 100)

    def test_output_is_new_child_directory_only(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = reserve_output(root, 'new')
            marker = target / 'preserve.txt'
            marker.write_text('keep')
            with self.assertRaises(FileExistsError):
                reserve_output(root, 'new')
            self.assertEqual(marker.read_text(), 'keep')
            with self.assertRaises(ValueError):
                reserve_output(root, '../escape')


if __name__ == '__main__':
    unittest.main()
