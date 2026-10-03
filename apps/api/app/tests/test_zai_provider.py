import asyncio

import pytest

from app.ai.providers.base import ContentBlock, ProviderTool, ProviderTurn
from app.ai.providers.zai import ZaiProvider, credential_slot


@pytest.mark.asyncio
async def test_native_tools_and_free_configuration(monkeypatch):
    provider = ZaiProvider()
    captured = {}

    async def post(url, key, payload):
        captured.update(payload)
        assert url == 'https://api.z.ai/api/paas/v4/chat/completions'
        return {'choices': [{'message': {'content': None, 'tool_calls': [
            {'id': 'call1', 'function': {'name': 'market__prices', 'arguments': '{"symbol":"OGDC"}'}}
        ]}, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}}

    monkeypatch.setattr(provider, '_post', post)
    result = await provider.tool_chat('test-credential', [ProviderTurn('user', [ContentBlock('text', text='price')])],
                                     [ProviderTool('market.prices', 'prices', {'type': 'object'})])
    assert captured['model'] == 'glm-4.7-flash'
    assert captured['thinking'] == {'type': 'disabled'}
    assert captured['max_tokens'] == 4096
    assert captured['tools'][0]['type'] == 'function'
    assert all(t['type'] != 'web_search' for t in captured['tools'])
    assert result.turn.content[0].name == 'market.prices'
    assert result.turn.content[0].arguments == {'symbol': 'OGDC'}
    assert result.input_tokens == 100


@pytest.mark.asyncio
async def test_same_credential_is_serialized_and_released_on_failure(monkeypatch):
    from app.ai.providers import zai
    monkeypatch.setattr(zai.engine.dialect, 'name', 'sqlite')
    active = 0
    maximum = 0

    async def run():
        nonlocal active, maximum
        async with credential_slot('test-credential'):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(run(), run(), run())
    assert maximum == 1
    with pytest.raises(RuntimeError):
        async with credential_slot('test-credential'):
            raise RuntimeError('failure')
    await asyncio.wait_for(run(), 1)


@pytest.mark.asyncio
async def test_postgres_slot_waits_and_unlocks_on_error(monkeypatch):
    from app.ai.providers import zai
    statements = []
    answers = iter([False, True])

    class Result:
        def scalar(self):
            return next(answers)

    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def commit(self): pass
        def execute(self, statement, parameters):
            statements.append(str(statement))
            return Result()

    class Engine:
        class dialect:
            name = 'postgresql'
        def connect(self): return Connection()

    monkeypatch.setattr(zai, 'engine', Engine())
    with pytest.raises(RuntimeError):
        async with credential_slot('test-pg-credential'):
            raise RuntimeError('transport failed')
    assert sum('pg_try_advisory_lock' in s for s in statements) == 2
    assert 'pg_advisory_unlock' in statements[-1]
