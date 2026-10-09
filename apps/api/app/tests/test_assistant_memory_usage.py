import json

import pytest
from sqlalchemy import select

from app.ai.providers.http_placeholders import AnthropicProvider
from app.ai import token_counting
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantAttempt, AssistantExecution
from app.models.workstation import AssistantMessage
from app.models.assistant_workspace import ConversationSummary
from app.models.workstation import Conversation
from app.services import assistant_memory
from app.services.assistant_policy import selected_policy
from app.tests.support.assistant import accepted


def summary_case(client, monkeypatch, **overrides):
    _, user_id, identifier, conversation_id = accepted(client)
    policy = selected_policy() | {'history': 4000, 'recent': 300, 'summary': 100, **overrides}
    with SessionLocal.begin() as db:
        for index in range(8):
            db.add(AssistantMessage(conversation_id=conversation_id, role='user',
                content=f'Requirement {index}: ' + 'dated conversation context ' * 10))
        db.get(AssistantExecution, identifier).policy_json = json.dumps(policy)
    monkeypatch.setattr(assistant_memory, 'execution_policy', lambda: policy)
    monkeypatch.setattr(assistant_memory, 'estimate_tokens', lambda value: 4500 if isinstance(value, list) else 150)
    monkeypatch.setattr(token_counting, 'local_input_count', lambda *_: (100, 'fixture_estimate'))
    return user_id, identifier, conversation_id


@pytest.mark.asyncio
async def test_summary_provider_usage_is_measured_reserved_and_counted(client, monkeypatch):
    user, execution, conversation = summary_case(client, monkeypatch)
    provider = AnthropicProvider()
    sent = []
    async def post(_url, _key, payload):
        sent.append(payload)
        return {'model': 'fixture-model', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': 'Preserve the dated requirements.'}],
            'usage': {'input_tokens': 37, 'output_tokens': 8, 'cache_read_input_tokens': 5}}
    monkeypatch.setattr(provider, '_post', post)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    usage = assistant_memory.summary_provider_usage(execution)
    assert usage['model_calls'] == 1 and usage['input_tokens'] == 37 and usage['output_tokens'] == 8
    assert usage['cache_read_tokens'] == 5 and usage['unknown_usage_calls'] == 0
    assert usage['reported_input_for_all_calls'] and usage['reported_output_for_all_calls']
    assert usage['transmitted_input_bytes'] > 0 and len(sent) == 1
    with SessionLocal() as db:
        row = db.get(AssistantExecution, execution)
        accounting = json.loads(row.accounting_json)
        assert accounting['calls'] == 1 and accounting['output'] == 8
        assert row.reserved_input_tokens == 37
        attempt = db.scalar(select(AssistantAttempt).where(AssistantAttempt.execution_id == execution))
        assert attempt.operation == 'conversation_summary' and attempt.status == 'completed'
        assert json.loads(attempt.metadata_json)['wire_payload_sha256']


@pytest.mark.asyncio
async def test_failed_sent_summary_has_unknown_usage_without_fabricated_tokens(client, monkeypatch):
    user, execution, conversation = summary_case(client, monkeypatch)
    provider = AnthropicProvider()
    async def post(*_args):
        raise TimeoutError('fixture')
    monkeypatch.setattr(provider, '_post', post)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    usage = assistant_memory.summary_provider_usage(execution)
    assert usage['model_calls'] == usage['unknown_usage_calls'] == 1
    assert usage['input_tokens'] == usage['output_tokens'] == 0
    assert not usage['reported_input_for_all_calls'] and not usage['reported_output_for_all_calls']
    with SessionLocal() as db:
        row = db.get(AssistantExecution, execution)
        ledger = json.loads(row.accounting_json)
        assert ledger['summaries'][0]['input_tokens'] is None
        assert ledger['summaries'][0]['output_tokens'] is None
        assert ledger['calls'] == 1 and ledger['output'] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [{'cumulative_input': 99}, {'calls': 0}, {'cumulative_output': 0}])
async def test_summary_budget_rejection_does_not_record_a_sent_call(client, monkeypatch, overrides):
    user, execution, conversation = summary_case(client, monkeypatch, **overrides)
    provider = AnthropicProvider()
    sent = []
    async def post(*_args):
        sent.append(True)
        raise AssertionError('Provider must not be called')
    monkeypatch.setattr(provider, '_post', post)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    assert not sent
    usage = assistant_memory.summary_provider_usage(execution)
    assert usage['model_calls'] == usage['unknown_usage_calls'] == 0
    with SessionLocal() as db:
        row = db.get(AssistantExecution, execution)
        assert row.reserved_input_tokens == 0
        assert json.loads(row.accounting_json)['summaries'][0]['sent'] is False


@pytest.mark.asyncio
async def test_completed_summary_recovery_counts_once_and_reconciles_once(client, monkeypatch):
    user, execution, conversation = summary_case(client, monkeypatch)
    provider = AnthropicProvider()
    sent = []
    async def post(*_args):
        sent.append(True)
        return {'model': 'fixture-model', 'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': 'Keep requirements dated.'}],
            'usage': {'input_tokens': 37, 'output_tokens': 8}}
    monkeypatch.setattr(provider, '_post', post)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    with SessionLocal.begin() as db:
        for summary in db.scalars(select(ConversationSummary)):
            db.delete(summary)
        row = db.get(AssistantExecution, execution)
        accounting = json.loads(row.accounting_json)
        accounting['summaries'] = []
        accounting['output'] = 100
        row.accounting_json = json.dumps(accounting)
        attempt = db.scalar(select(AssistantAttempt).where(AssistantAttempt.execution_id == execution))
        metadata = json.loads(attempt.metadata_json)
        metadata.pop('summary_output_reconciled')
        attempt.metadata_json = json.dumps(metadata)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    assert len(sent) == 1 and assistant_memory.summary_provider_usage(execution)['model_calls'] == 1
    with SessionLocal() as db:
        accounting = json.loads(db.get(AssistantExecution, execution).accounting_json)
        assert accounting['calls'] == 1 and accounting['output'] == 8
        assert accounting['summaries'][0]['recovered'] is True


@pytest.mark.asyncio
async def test_explicit_retry_does_not_reuse_a_rejected_completed_summary(client, monkeypatch):
    user, execution, conversation = summary_case(client, monkeypatch)
    provider = AnthropicProvider()
    reasons = ['max_tokens', 'end_turn']
    async def post(*_args):
        return {'model': 'fixture-model', 'stop_reason': reasons.pop(0),
            'content': [{'type': 'text', 'text': 'Keep requirements dated.'}],
            'usage': {'input_tokens': 37, 'output_tokens': 8}}
    monkeypatch.setattr(provider, '_post', post)
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    with SessionLocal.begin() as db:
        db.get(Conversation, conversation).summary_failure = None
    await assistant_memory.prepare(execution, user, conversation, provider, 'fixture-key', 'fixture-model')
    assert not reasons
    assert assistant_memory.summary_provider_usage(execution)['model_calls'] == 2
