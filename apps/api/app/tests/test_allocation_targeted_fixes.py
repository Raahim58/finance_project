"""Offline regression checks for verified failures, without provider requests."""
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.ai.providers.base import ContentBlock, LLMProviderResult
from app.ai.tool_loop import ToolExecution, _budget_limit_answer, _record_provider_result, _render_allocation, _result_blocks
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution, AssistantStage, AssistantAttempt
from app.models.user import User
from app.models.workstation import Conversation
from app.services import assistant_diagnostics as diagnostics
from app.services.canonical_market_service import observation_trade_date, price_series, latest_price, canonical_prices_for_date
from app.services.market_ingestion import persist_market_data
from app.services.market_providers import LatestPriceRow
from app.tools.quant_tools import AllocationVerificationInput
from app.tools.registry import tool_result


def arguments(proposal):
    return {'portfolio_id': 'p', 'allowed_instrument_ids': ['i'], 'proposal': proposal}


def test_string_proposal_retains_strict_object_validation():
    proposal = {'legs': [{'instrument_id': 'i', 'side': 'buy', 'gross_amount': 100}]}
    assert AllocationVerificationInput.model_validate(arguments(proposal)) == AllocationVerificationInput.model_validate(arguments(json.dumps(proposal)))


@pytest.mark.parametrize('value', ['not json', '[]', '"{}"', '{"legs":[{"instrument_id":"i","side":"hold","gross_amount":100}]}', '{"legs":[{"instrument_id":"i","side":"buy","gross_amount":-1}]}', '{"unexpected":true}'])
def test_invalid_string_proposal_is_rejected(value):
    with pytest.raises(ValidationError):
        AllocationVerificationInput.model_validate(arguments(value))


def calculation():
    return {'accepted': False, 'errors': ['binding_constraint_check_unavailable'],
            'trade_feasibility': 'valid', 'IPS_status': 'incomplete', 'evidence_status': 'limited',
            'legs': [{'instrument_id': 'i', 'symbol': 'TEST', 'required_statement': 'Buy 1 share.', 'quantity': '1'}],
            'current_weights': {'i': .5, 'CASH': .5}, 'proposed_weights': {'i': .6, 'CASH': .4},
            'evidence_versions': {'i': {'symbol': 'TEST', 'currency': 'PKR'}},
            'comparison': {'metrics': [{'key': 'volatility', 'current': .19, 'proposed': .180406}], 'duplicate': 'x' * 10000},
            'proposed_compliance': {'status': 'NOT_EVALUATED', 'checks': [{'code': 'target_beta', 'status': 'NOT_EVALUATED', 'limit': 1}], 'violations': [], 'not_evaluated': [{'code': 'target_beta', 'status': 'NOT_EVALUATED', 'limit': 1}]},
            'checks': {'price_freshness': {'status': 'stale', 'instruments': {'i': {'status': 'stale', 'policy': {'intervening_sessions': ['date'] * 36}}}}}}


def test_model_projection_preserves_full_result_and_citation_id():
    full = calculation()
    checkpoint = {'tool_trace': [], 'evidence': {}, 'next_evidence': 1}
    envelope = tool_result('ok', full, sources=[{'source_name': 'Server allocation verification', 'price_observations': {'i': {'source_url': 'https://example.com'}}}])
    execution = ToolExecution(ContentBlock('tool_call', id='call', name='allocation.verify'), envelope, 1)
    blocks = _result_blocks(checkpoint, execution)
    result = blocks[0].result
    assert checkpoint['allocation_calculations']['call']['comparison']['duplicate'] == 'x' * 10000
    assert result['data']['metrics'][0]['proposed'] == .180406
    assert result['data']['checks']['ips_compliance']['checks'][0]['code'] == 'target_beta'
    assert result['data']['checks']['price_freshness']['coverage'] == {'i': 36}
    assert result['sources'][0]['evidence_ref'] == 'E1'
    assert checkpoint['evidence']['E1']['source']['price_observations']
    assert len(json.dumps(result)) < len(json.dumps(envelope)) / 3
    assert 'comparison' not in result['data']


def test_feasible_incomplete_candidate_is_visible_but_not_accepted():
    text, outcome = _render_allocation({'allocation_check': calculation()})
    assert outcome['status'] == 'rejected'
    assert outcome['IPS_status'] == 'incomplete'
    assert len(outcome['rows']) == 2
    assert 'not fully IPS' in text
    assert 'target_beta' in text
    invalid = calculation(); invalid['trade_feasibility'] = 'invalid'
    _, outcome = _render_allocation({'allocation_check': invalid})
    assert not outcome['rows']


def test_local_budget_fallback_does_not_increment_provider_usage():
    checkpoint = {'usage': {'model_calls': 2}}
    _record_provider_result(checkpoint, LLMProviderResult(content='limit', provider='mock', model='mock', finish_reason='budget_limit'))
    assert checkpoint['usage'] == {'model_calls': 2}


def test_limit_notice_preserves_partial_and_citations_not_raw_metadata():
    checkpoint = {'turns': [{'role': 'assistant', 'content': [{'type': 'text', 'text': 'Partial analysis [[E1]]'}]}],
                  'evidence': {'E1': {'identity': 'PRIVATE_METADATA', 'source': {'source_name': 'Portfolio'}}}}
    text = _budget_limit_answer(checkpoint, 'input per call')
    assert 'Partial analysis [[E1]]' in text
    assert 'input per call' in text
    assert 'Portfolio [[E1]]' in text
    assert 'PRIVATE_METADATA' not in text


def test_rejected_preflight_is_saved_without_attempt_or_reservation():
    with SessionLocal.begin() as db:
        user = User(email='preflight@example.com', password_hash='fixture'); db.add(user); db.flush()
        conversation = Conversation(user_id=user.id, title='Fixture'); db.add(conversation); db.flush()
        execution = AssistantExecution(user_id=user.id, conversation_id=conversation.id, client_request_id='fixture', request_hash='fixture', request_encrypted='fixture', policy_json='{}')
        db.add(execution); db.flush(); identifier = execution.id
    token = diagnostics.execution_id.set(identifier)
    try:
        diagnostics.record_preflight_rejection({'counted_input_tokens': 50000, 'per_call_limit': 48000, 'rejected_boundary': 'per_call_input', 'input_count_method': 'fixture'})
    finally:
        diagnostics.execution_id.reset(token)
    with SessionLocal() as db:
        stage = db.scalar(select(AssistantStage).where(AssistantStage.execution_id == identifier))
        assert stage.status == 'rejected'
        assert json.loads(stage.metadata_json)['counted_input_tokens'] == 50000
        assert db.get(AssistantExecution, identifier).reserved_input_tokens == 0


def test_exchange_date_uses_local_date_and_explicit_source_date():
    observation = SimpleNamespace(effective_at=datetime(2026, 8, 12, 19, tzinfo=UTC), values_json='{}')
    assert observation_trade_date(observation) == date(2026, 8, 13)
    assert observation_trade_date(observation, {'trade_date': '2026-08-14'}) == date(2026, 8, 14)


def test_exchange_date_filters_cover_source_day_only():
    from decimal import Decimal
    row = LatestPriceRow(symbol='DATEFIX', trade_date=date(2026, 8, 13), close=Decimal(100), previous_close=Decimal(99), open=Decimal(99), high=Decimal(101), low=Decimal(98), volume=10, name='Date fixture', sector='Test', source_url='https://dps.psx.com.pk/fixture')
    with SessionLocal() as db:
        persist_market_data(db, latest_prices=[row], source='dps')
        assert price_series(db, 'DATEFIX', start=date(2026, 8, 13), end=date(2026, 8, 13))[0].trade_date == row.trade_date
        assert price_series(db, 'DATEFIX', end=date(2026, 8, 12)) == []
        assert latest_price(db, 'DATEFIX', as_of=date(2026, 8, 12)) is None
        assert canonical_prices_for_date(db, date(2026, 8, 13))[0].trade_date == row.trade_date


@pytest.mark.parametrize('violations,missing,errors,expected_ips,expected_trade', [
    ([], [], [], 'pass', 'valid'),
    ([{'code': 'target_volatility'}], [], [], 'breach', 'valid'),
    ([], [{'code': 'target_beta'}], [], 'incomplete', 'valid'),
    ([{'code': 'target_volatility'}], [{'code': 'target_beta'}], [], 'breach_and_incomplete', 'valid'),
    ([], [], ['overselling'], 'pass', 'invalid'),
])
def test_verifier_outcomes_follow_existing_calculation_and_checks(monkeypatch, violations, missing, errors, expected_ips, expected_trade):
    from decimal import Decimal
    from app.services import allocation_verification as service
    from app.reasoning.allocation import AllocationProposal
    instrument = SimpleNamespace(id='i', symbol='TEST', sector='Test', currency='PKR', instrument_type='equity', metadata_json='{}')
    summary = SimpleNamespace(holdings=[SimpleNamespace(symbol='TEST', quantity=1)], cash_balance=Decimal(100), valuation_complete=True,
                              portfolio=SimpleNamespace(base_currency='PKR', selected_ips_version_id='ips'))
    db = SimpleNamespace(scalars=lambda *_: [instrument])
    monkeypatch.setattr(service, 'get_portfolio_summary', lambda *_: summary)
    monkeypatch.setattr(service, 'latest_price', lambda *_: SimpleNamespace(close=100, source='fixture', source_url=None, trade_date=date(2026,8,13), artifact_id=None, artifact_sha256=None))
    monkeypatch.setattr(service, 'price_freshness', lambda *_: {'status': 'current'})
    monkeypatch.setattr(service, '_selected_ips_constraints', lambda *_: {})
    compliance = {'status': 'BREACH' if violations else 'NOT_EVALUATED' if missing else 'PASS', 'checks': [], 'violations': violations, 'not_evaluated': missing}
    monkeypatch.setattr(service, 'evaluate_ips_constraints', lambda *_args, **_kwargs: compliance)
    monkeypatch.setattr(service, 'calculate_allocation', lambda *_: {'errors': list(errors), 'current_weights': {'i': .5, 'CASH': .5}, 'proposed_weights': {'i': .5, 'CASH': .5}, 'current_cash': '100', 'proposed_cash': '100'})
    monkeypatch.setattr(service, 'compare_portfolio', lambda *_args, **_kwargs: {'current_compliance': compliance, 'metrics': [], 'proposed_risk_contributions': [], 'assumptions': {'expected_return_method':'fixture'}})
    result = service.verify_allocation(db, None, 'p', AllocationProposal(), ['i'])
    assert result['IPS_status'] == expected_ips
    assert result['trade_feasibility'] == expected_trade
    assert result['accepted'] is (not violations and not missing and not errors)


def test_live_execution_preflight_stops_before_provider_and_preserves_diagnostic(client, monkeypatch):
    from app.tests.test_phase8_phase2_tool_loop import _auth_with_anthropic
    from app.ai.providers.http_placeholders import AnthropicProvider
    headers, _ = _auth_with_anthropic(client, monkeypatch, email='preflight-loop@example.com')
    provider = AnthropicProvider()
    sent = []
    async def forbidden_call(*_args):
        sent.append(True)
        raise AssertionError('Provider must not be called')
    async def oversized(*_args, **_kwargs):
        return 50000, {'input_count_method': 'fixture_provider_count'}
    monkeypatch.setattr(provider, '_post', forbidden_call)
    monkeypatch.setattr('app.ai.tool_loop.get_provider', lambda _: provider)
    monkeypatch.setattr('app.ai.token_counting.preflight_count', oversized)
    response = client.post('/assistant/messages', headers=headers, json={'question':'Review my portfolio', 'provider':'anthropic'})
    assert response.status_code == 201, response.text
    assert sent == []
    result = response.json()
    assert result['synthesis']['token_usage']['model_calls'] == 0
    assert 'input per call' in result['answer']
    with SessionLocal() as db:
        assert not list(db.scalars(select(AssistantAttempt)))
        stage = db.scalar(select(AssistantStage).where(AssistantStage.operation == 'provider_input_preflight'))
        assert json.loads(stage.metadata_json)['counted_input_tokens'] == 50000


def test_public_allocation_schema_preserves_separate_outcomes():
    from app.schemas.assistant import AllocationResult
    value = AllocationResult.model_validate({'status':'rejected', 'trade_feasibility':'valid', 'IPS_status':'incomplete', 'evidence_status':'limited'}).model_dump()
    assert value['trade_feasibility'] == 'valid'
    assert value['IPS_status'] == 'incomplete'
    assert value['evidence_status'] == 'limited'
