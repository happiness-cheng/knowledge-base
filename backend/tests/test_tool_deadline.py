import json
from threading import Event
from time import perf_counter
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models.node import KnowledgeNode
from app.services import agent_tools


@pytest.fixture
def release():
    event = Event()
    try:
        yield event
    finally:
        event.set()
        getattr(agent_tools, 'close_tool_executor', lambda **kwargs: None)(wait=True)


def test_timeout_returns_before_uncancellable_work_finishes(monkeypatch, release):
    def slow(*args, **kwargs):
        release.wait(0.75)
        return '[]'
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, 'search_knowledge_base', slow)
    monkeypatch.setattr(agent_tools, 'TOOL_TIMEOUT_SECONDS', 0.02)
    started = perf_counter()
    result = agent_tools.execute_tool('search_knowledge_base', {'query': 'q'}, None)
    elapsed = perf_counter() - started
    assert 'timed out' in json.loads(result)['error']
    assert elapsed < 0.25


def test_timed_out_jobs_keep_capacity_until_they_actually_finish(monkeypatch, release):
    def slow(*args, **kwargs):
        release.wait(1)
        return '[]'
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, 'search_knowledge_base', slow)
    monkeypatch.setattr(agent_tools, 'TOOL_TIMEOUT_SECONDS', 0.02)
    for _ in range(4):
        assert 'timed out' in agent_tools.execute_tool('search_knowledge_base', {}, None)
    started = perf_counter()
    response = json.loads(agent_tools.execute_tool('search_knowledge_base', {}, None))
    assert 'capacity' in response['error']
    assert perf_counter() - started < 0.25


def test_file_sql_tool_gets_its_own_session(monkeypatch, tmp_path, release):
    engine = create_engine(f"sqlite:///{tmp_path / 'tool.db'}", connect_args={'check_same_thread': False})
    try:
        with Session(engine) as caller:
            def inspect(_arguments, tool_db, **kwargs):
                return json.dumps({'shared': tool_db is caller, 'select': tool_db.execute(text('SELECT 1')).scalar()})
            monkeypatch.setitem(agent_tools.TOOL_HANDLERS, 'get_node_details', inspect)
            response = json.loads(agent_tools.execute_tool('get_node_details', {'node_id': 1}, caller))
            assert response == {'shared': False, 'select': 1}
    finally:
        engine.dispose()


def test_uncommitted_caller_changes_are_not_implicitly_flushed_or_committed(monkeypatch, tmp_path, release):
    engine = create_engine(f"sqlite:///{tmp_path / 'pending.db'}")
    Base.metadata.create_all(engine)
    handler = Mock(return_value='[]')
    monkeypatch.setitem(agent_tools.TOOL_HANDLERS, 'get_node_details', handler)
    try:
        with Session(engine) as caller:
            caller.add(KnowledgeNode(id=1, user_id=1, title='pending', content='not saved'))
            response = json.loads(agent_tools.execute_tool('get_node_details', {'node_id': 1}, caller))
            assert 'committed' in response['error']
            handler.assert_not_called()
            assert len(caller.new) == 1
    finally:
        engine.dispose()
