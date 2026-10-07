"""Offline evidence-fusion contracts; no provider or ingestion requests."""
import json
from app.ai.company_packet import PACKET_PREFIX, initial_calls, merge_result, model_packet, new_packet, project_turns
from app.ai.providers.base import ContentBlock, ProviderTurn
from app.tools.registry import expand_model_data, tool_result


def call(name='research.company_sections', **args):
    return ContentBlock('tool_call', id='read-1', name=name, arguments={'instrument_id': 'luck', 'sections': ['company_facts'], **args})


def fact(value, start, end, **extra):
    return dict(metric='revenue', period_type='annual', unit='million', currency='PKR', accounting_basis='consolidated', value=value, period_start=start, period_end=end, **extra)


def facts(packet, rows):
    merge_result(packet, call(), tool_result('ok', {'sections': [{'name': 'company_facts', 'state': 'ready', 'data': {'fundamentals': rows}, 'evidence_refs': ['filing']}]}, sources=[{'evidence_id': 'filing', 'evidence_ref': 'E1', 'source_url': 'https://source.test/report'}]))


def test_changes_keep_period_basis_citations_and_do_not_mix_units():
    packet = new_packet({})
    facts(packet, [fact('100', '2024-07-01', '2025-06-30'), fact('150', '2025-07-01', '2026-06-30'), fact('200', '2025-07-01', '2026-06-30') | {'unit': 'thousand'}])
    trend, = packet['financial_trends']
    assert trend['absolute_change'] == '50'
    assert trend['relative_change'] == '0.5'
    assert trend['previous_period'] == ['2024-07-01', '2025-06-30']
    assert trend['evidence_refs'] == ['E1']
    section, = expand_model_data(model_packet(packet))['financials']
    assert section['data']['sections'][0]['evidence_refs'] == ['E1']


def test_conflicting_values_are_not_accepted_as_a_trend():
    packet = new_packet({})
    facts(packet, [fact('100', '2024-07-01', '2025-06-30'), fact('150', '2025-07-01', '2026-06-30'), fact('999', '2025-07-01', '2026-06-30')])
    assert not packet['financial_trends']
    assert packet['contradictions'][0]['values'] == ['150', '999']


def test_unknown_basis_and_different_interim_duration_do_not_produce_growth():
    packet = new_packet({})
    facts(packet, [fact('100', '2025-07-01', '2025-09-30') | {'period_type': 'interim'}, fact('150', '2025-07-01', '2026-03-31') | {'period_type': 'interim'}])
    assert not packet['financial_trends']
    packet = new_packet({})
    facts(packet, [fact('100', '2024-07-01', '2025-06-30') | {'accounting_basis': None}, fact('150', '2025-07-01', '2026-06-30') | {'accounting_basis': None}])
    assert not packet['financial_trends']


def test_pagination_deduplicates_without_losing_text_or_failing_read():
    packet = new_packet({})
    c = call('research.search', query='oil', cursor=None)
    merge_result(packet, c, tool_result('ok', {'chunks': [{'id': 'a', 'text': 'Evidence'}]}, remaining=3, continuation='next'))
    merge_result(packet, call('research.search', query='oil', cursor='next'), tool_result('ok', {'chunks': [{'id': 'a'}, {'id': 'b', 'text': 'More'}]}, remaining=0))
    section, = packet['sections'].values()
    assert section['data']['chunks'] == [{'id': 'a', 'text': 'Evidence'}, {'id': 'b', 'text': 'More'}]
    assert section['coverage']['remaining'] == 0
    merge_result(packet, c, tool_result('unavailable', error={'code': 'tool_timeout'}))
    assert section['data']['chunks'][0]['text'] == 'Evidence'
    assert section['follow_up_failure']['data']['error']['code'] == 'tool_timeout'


def test_planning_bounds_and_preserves_selected_portfolio_scope():
    identity = {'portfolio': {'portfolio_id': 'mine'}, 'explicit_instrument': {'instrument_id': 'luck', 'symbol': 'LUCK'}}
    calls = initial_calls(identity, 'Does LUCK fit my portfolio?', False, 12)
    assert len(calls) == 8
    assert calls[0].arguments == {'portfolio_id': 'mine'}
    assert calls[-1].name == 'research.search'
    assert all(c.arguments.get('portfolio_id') is None for c in initial_calls(identity, 'Review LUCK', True, 12))
    assert [c.name for c in initial_calls(identity, 'What is LUCK latest price?', False, 12)] == ['market.latest']
    assert not initial_calls(identity, 'Review LUCK', False, 4)


def test_projection_preserves_native_ids_reasoning_images_and_original_turns():
    packet = new_packet({})
    c = call('market.latest')
    envelope = tool_result('ok', {'price': '100', 'date': '2026-10-02'}, sources=[{'evidence_ref': 'E1', 'id': 'price-1', 'source_url': 'https://source.test'}])
    merge_result(packet, c, envelope)
    turns = [ProviderTurn('user', [ContentBlock('text', text='Question')]), ProviderTurn('assistant', [c], {'reasoning_content': 'private reasoning'}), ProviderTurn('user', [ContentBlock('tool_result', id=c.id, name=c.name, result=envelope, opaque={'include_id': True}), ContentBlock('image', data='image', mime_type='image/png')])]
    projected = project_turns(turns, packet, [c.id])
    assert projected[1].opaque == turns[1].opaque
    assert projected[2].content[0].opaque == {'include_id': True}
    assert projected[2].content[1] == turns[2].content[1]
    assert projected[2].content[-1].text.startswith(PACKET_PREFIX)
    assert turns[2].content[0].result == envelope
    assert 'private reasoning' not in json.dumps(model_packet(packet))


def test_projection_is_smaller_for_repeated_evidence_and_preserves_sources():
    packet = new_packet({})
    c = call('research.search', query='oil')
    envelope = tool_result('ok', {'chunks': [{'id': 'article-1', 'text': 'Oil development. ' * 500}]}, sources=[{'evidence_ref': 'E1', 'id': 'article-1', 'quote_snippet': 'Oil development. ' * 500, 'source_url': 'https://source.test/oil'}])
    merge_result(packet, c, envelope)
    turns = [ProviderTurn('user', [ContentBlock('text', text='Question')])]
    for n in range(3):
        turns += [ProviderTurn('assistant', [ContentBlock('tool_call', id=f't{n}', name=c.name, arguments=c.arguments)]), ProviderTurn('user', [ContentBlock('tool_result', id=f't{n}', name=c.name, result=envelope)])]
    projected = project_turns(turns, packet, ['t0', 't1', 't2'])
    old = len(json.dumps([t.to_dict() for t in turns]))
    new = len(json.dumps([t.to_dict() for t in projected]))
    assert new < old / 2
    assert packet['sources']['E1']['source_url'] == 'https://source.test/oil'


def test_first_pass_recovery_reuses_saved_plan_and_reservation(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.ai import tool_loop
    identity = {'explicit_instrument': {'instrument_id': 'luck', 'symbol': 'LUCK'}}
    planned = initial_calls(identity, 'Review LUCK', True, 12)
    checkpoint = {'compact_evidence_enabled': True, 'resolved_identity': identity,
        'initial_evidence_plan': [c.to_dict() for c in planned],
        'reserved_tool_calls': len(planned), 'reserved_tool_call_ids': [c.id for c in planned],
        'completed_tool_call_ids': [planned[0].id], 'evidence': {}, 'next_evidence': 1,
        'tool_trace': [], 'turns': [ProviderTurn('system', [ContentBlock('text', text='Instructions')]).to_dict()],
        'evidence_packet': new_packet(identity)}
    called, active, peak = [], 0, 0
    async def fake_tool(user_id, c):
        nonlocal active, peak
        assert user_id == 'owner'
        called.append(c.id)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return tool_loop.ToolExecution(c, tool_result('missing', {'reason': 'fixture absence'}), 1)
    monkeypatch.setattr(tool_loop, '_execute_tool', fake_tool)
    monkeypatch.setattr(tool_loop, '_save_checkpoint', lambda *_: None)
    payload = SimpleNamespace(question='Review LUCK', company_only=True)
    asyncio.run(tool_loop._prepare_evidence('execution', 'owner', payload, checkpoint))
    assert called == [c.id for c in planned[1:]]
    assert checkpoint['reserved_tool_calls'] == len(planned)
    assert checkpoint['completed_tool_call_ids'] == [c.id for c in planned]
    assert peak == 4
    asyncio.run(tool_loop._prepare_evidence('execution', 'owner', payload, checkpoint))
    assert len(called) == len(planned) - 1
    assert checkpoint['initial_evidence_prepared']


def test_actual_loop_has_evidence_before_first_model_call_and_no_summary_call(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "assistant_company_digest_enabled", False)
    from app.tests.test_phase8_phase2_tool_loop import _auth_with_anthropic, _mock_market
    from app.ai.providers.http_placeholders import AnthropicProvider
    from app.ai.tool_loop import ToolExecution
    from app.core.security import decrypt_secret
    from app.db.session import SessionLocal
    from app.models.assistant_execution import AssistantExecution
    from sqlalchemy import select
    headers, user_id = _auth_with_anthropic(client, monkeypatch, email='packet-loop@example.com')
    instrument = next(row for row in _mock_market(monkeypatch) if row.symbol == 'MEBL')
    provider, captured, called = AnthropicProvider(), [], []
    async def fake_tool(owner, c):
        assert owner == user_id
        called.append(c.name)
        return ToolExecution(c, tool_result('ok', {'instrument_id': instrument.id, 'value': '100', 'period_end': '2026-06-30'}, sources=[{'id': 'fixture', 'source_name': 'Offline fixture', 'source_url': 'https://source.test/fixture'}]), 1)
    async def fake_post(_url, _key, request):
        captured.append(request)
        assert len(called) == 6
        texts = [b.get('text', '') for message in request['messages'] for b in message['content']]
        packet = expand_model_data(json.loads(next(t for t in texts if t.startswith(PACKET_PREFIX))[len(PACKET_PREFIX):]))
        assert packet['identity']['explicit_instrument']['instrument_id'] == instrument.id
        from app.ai.company_packet import PACKET_SECTIONS
        assert sum(len(packet[key]) for key in PACKET_SECTIONS) == 6
        # Document metadata is interned once; each reference keeps its own location.
        assert packet['source_documents'][packet['sources']['E1']['document_ref']]['source_url'] == 'https://source.test/fixture'
        return {'model': 'claude-test', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'Stored fact [[E1]].'}], 'usage': {'input_tokens': 200, 'output_tokens': 10}}
    monkeypatch.setattr(provider, '_post', fake_post)
    monkeypatch.setattr('app.ai.tool_loop.get_provider', lambda _: provider)
    monkeypatch.setattr('app.ai.tool_loop._execute_tool', fake_tool)
    response = client.post('/assistant/messages', headers=headers, json={'question': 'Review MEBL', 'instrument_id': instrument.id, 'provider': 'anthropic', 'company_only': True})
    assert response.status_code == 201, response.text
    assert len(captured) == 1
    assert response.json()['synthesis']['token_usage']['model_calls'] == 1
    assert response.json()['source_citations'][0]['source_url'] == 'https://source.test/fixture'
    with SessionLocal() as db:
        row = db.scalar(select(AssistantExecution).where(AssistantExecution.user_id == user_id))
        checkpoint = json.loads(decrypt_secret(row.transcript_encrypted))
        assert checkpoint['reserved_tool_calls'] == 6
        assert checkpoint['compact_evidence_enabled'] is True


def test_partial_period_is_not_compared_to_full_period():
    packet = new_packet({})
    facts(packet, [fact('100', '2024-07-01', '2025-06-30'), fact('150', '2025-07-15', '2026-06-30')])
    assert not packet['financial_trends']


def test_company_fact_pages_merge_and_equivalent_decimal_values_are_not_conflicts():
    packet = new_packet({})
    older = fact('100.0', '2024-07-01', '2025-06-30', id='old')
    current = fact('150', '2025-07-01', '2026-06-30', id='new')
    facts(packet, [older, current])
    facts(packet, [older | {'value': '100'}, current])
    section, = packet['sections'].values()
    assert len(section['data']['sections']) == 1
    assert len(section['data']['sections'][0]['data']['fundamentals']) == 2
    assert not packet['contradictions']
    assert len(packet['financial_trends']) == 1


def test_initial_quant_projection_preserves_original_and_followup_can_expand():
    packet = new_packet({})
    c = ContentBlock('tool_call', id='initial-3', name='quant.portfolio', arguments={'portfolio_id': 'owned'})
    raw = {'portfolio': {'annualized_return': '0.12'}, 'sample_size': 1200,
           'annualization': 252, 'covariance': [[1, 2], [2, 3]], 'correlation': [[1, .5], [.5, 1]],
           'rolling': {'portfolio_volatility': [0.2] * 1200}, 'warnings': ['Not a forecast']}
    envelope = tool_result('ok', raw)
    merge_result(packet, c, envelope)
    section, = packet['sections'].values()
    assert section['data']['sample_size'] == 1200
    assert section['data']['portfolio'] == raw['portfolio']
    assert 'covariance' not in section['data']
    assert expand_model_data(envelope['data']) == raw
    merge_result(packet, ContentBlock('tool_call', id='model-requested', name=c.name, arguments=c.arguments), envelope)
    assert packet['sections'][next(iter(packet['sections']))]['data']['covariance'] == raw['covariance']


def test_company_cache_is_reusable_but_basis_corrections_invalidate_it():
    from datetime import date
    from app.tests.test_phase7a_canonical_context import _seed_user_and_market, _company_request
    from app.db.session import SessionLocal
    from app.models.user import User
    from app.models.workstation import FinancialFact
    from app.schemas.intelligence_context import ContextSectionName
    from app.services.context_builder import ContextBuilder
    user_id, instrument_id = _seed_user_and_market('packet-cache@example.com')
    builder = ContextBuilder()
    request = _company_request(ContextSectionName.COMPANY_FACTS)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        row = FinancialFact(instrument_id=instrument_id, taxonomy_key='revenue',
            period_type='annual', period_start=date(2025, 7, 1), period_end=date(2026, 6, 30),
            value=100, unit='million', currency='PKR', source_label='filing', consolidated=True)
        db.add(row); db.commit()
        first = builder.build(db, user, request)
        reused = builder.build(db, user, request)
        assert reused.sections['company_facts'].reused
        assert first.portfolio_id is None
        row.unit = 'thousand'
        row.consolidated = False
        db.commit()
        corrected = builder.build(db, user, request)
        assert not corrected.sections['company_facts'].reused
        assert corrected.sections['company_facts'].dependency_hash != first.sections['company_facts'].dependency_hash
        assert corrected.sections['company_facts'].data['fundamentals'][0]['accounting_basis'] == 'standalone'
        assert corrected.sections['company_facts'].data['fundamentals'][0]['unit'] == 'thousand'
        assert first.sections['company_facts'].data['fundamentals'][0]['unit'] == 'million'


def test_offline_legacy_and_compact_loop_comparison(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "assistant_company_digest_enabled", False)
    """Same fixture, real adapters, mocked transport; measure no network latency."""
    import time
    from app.tests.test_phase8_phase2_tool_loop import _auth_with_anthropic, _mock_market
    from app.ai.providers.http_placeholders import AnthropicProvider, wire_tool_name
    from app.ai.tool_loop import ToolExecution
    from app.core.config import settings
    headers, owner = _auth_with_anthropic(client, monkeypatch, email='packet-comparison@example.com')
    instrument = next(row for row in _mock_market(monkeypatch) if row.symbol == 'MEBL')
    plan = initial_calls({'explicit_instrument': {'instrument_id': instrument.id, 'symbol': 'MEBL'}}, 'Review MEBL', True, 12)
    provider, results = AnthropicProvider(), {}
    async def fake_tool(user_id, c):
        assert user_id == owner
        return ToolExecution(c, tool_result('ok', {'reported_fact': 'Fixture only', 'value': '100', 'period_end': '2026-06-30', 'unit': 'million PKR'}, sources=[{'id': 'same-source', 'source_name': 'Offline comparison fixture', 'source_url': 'https://fixture.test/report', 'quote_snippet': 'Fixture passage. ' * 150}]), 1)
    monkeypatch.setattr('app.ai.tool_loop.get_provider', lambda _: provider)
    monkeypatch.setattr('app.ai.tool_loop._execute_tool', fake_tool)
    for compact in (False, True):
        captured = []
        async def fake_post(_url, _key, request):
            captured.append(request)
            if not compact and len(captured) == 1:
                return {'model': 'claude-test', 'stop_reason': 'tool_use', 'content': [
                    {'type': 'tool_use', 'id': f'fixture-{n}', 'name': wire_tool_name(c.name), 'input': c.arguments} for n, c in enumerate(plan)], 'usage': {}}
            return {'model': 'claude-test', 'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': 'Fixture value 100 million PKR, period 2026-06-30 [[E1]].'}], 'usage': {}}
        monkeypatch.setattr(settings, 'assistant_compact_evidence_enabled', compact)
        monkeypatch.setattr(provider, '_post', fake_post)
        started = time.perf_counter()
        response = client.post('/assistant/messages', headers=headers, json={'question': 'Review MEBL', 'instrument_id': instrument.id, 'company_only': True, 'provider': 'anthropic'})
        assert response.status_code == 201, response.text
        result = response.json()
        results['compact' if compact else 'legacy'] = {'mock_provider_calls': len(captured),
            'backend_reads': len(result['tool_trace']),
            'serialized_request_bytes': sum(len(json.dumps(r, separators=(',', ':')).encode()) for r in captured),
            'offline_elapsed_ms': round((time.perf_counter() - started) * 1000, 2)}
        assert result['source_citations'][0]['source_url'] == 'https://fixture.test/report'
        assert '100 million PKR' in result['answer']
        assert '2026-06-30' in result['answer']
    assert results['compact']['mock_provider_calls'] == 1
    assert results['legacy']['mock_provider_calls'] == 2
    assert results['compact']['backend_reads'] == results['legacy']['backend_reads'] == 6
    assert results['compact']['serialized_request_bytes'] < results['legacy']['serialized_request_bytes']
    print('COMPANY_PACKET_COMPARISON=' + json.dumps(results, sort_keys=True))


def test_equal_length_non_overlapping_quarters_can_be_compared():
    packet = new_packet({})
    facts(packet, [fact('100', '2025-07-01', '2025-09-30') | {'period_type': 'quarterly'},
                   fact('120', '2025-10-01', '2025-12-31') | {'period_type': 'quarterly'}])
    assert packet['financial_trends'][0]['relative_change'] == '0.2'
    assert packet['financial_trends'][0]['current_period'] == ['2025-10-01', '2025-12-31']
    assert not packet['missing_data']


def test_missing_comparable_pair_is_explicit_with_pagination_coverage():
    packet = new_packet({})
    facts(packet, [fact('100', '2025-07-01', '2026-06-30')])
    assert packet['missing_data'][0]['code'] == 'no_comparable_financial_pair'
    assert 'coverage' in packet['missing_data'][0]


def test_citations_beside_financial_values_and_changes_use_exact_fact_sources():
    packet = new_packet({})
    rows = [fact('100', '2024-07-01', '2025-06-30', id='previous'),
            fact('150', '2025-07-01', '2026-06-30', id='current')]
    merge_result(packet, call(), tool_result('ok', {'sections': [{'name': 'company_facts', 'state': 'current',
        'data': {'fundamentals': rows}}]}, sources=[
        {'underlying_id': 'financial_fact:previous:v1', 'evidence_ref': 'E2'},
        {'underlying_id': 'financial_fact:current:v1', 'evidence_ref': 'E3'},
        {'underlying_id': 'financial_fact:unrelated:v1', 'evidence_ref': 'E4'}]))
    section, = packet['sections'].values()
    supplied = section['data']['sections'][0]['data']['fundamentals']
    assert supplied[0]['evidence_refs'] == ['E2']
    assert supplied[1]['evidence_refs'] == ['E3']
    assert packet['financial_trends'][0]['evidence_refs'] == ['E2', 'E3']


def test_existing_context_source_label_survives_citation_rendering():
    from app.ai.tool_loop import ToolExecution, _result_blocks, resolve_citations
    checkpoint = {'evidence': {}, 'next_evidence': 1, 'tool_trace': [], 'evidence_packet': new_packet({})}
    _result_blocks(checkpoint, ToolExecution(call(), tool_result('ok', {'value': '100'},
        sources=[{'evidence_id': 'filing', 'source': 'Stored annual filing', 'source_url': 'https://source.test/report'}]), 1))
    answer, sources, _ = resolve_citations('Stored value [[E1]].', checkpoint)
    assert 'Stored annual filing' in answer
    assert sources[0]['source_name'] == 'Stored annual filing'


def test_corrected_fact_replaces_old_value_and_its_citations():
    packet = new_packet({})
    for value, version, reference in [('100', 1, 'E1'), ('150', 2, 'E2')]:
        merge_result(packet, call(), tool_result('ok', {'sections': [{'name': 'company_facts', 'state': 'current',
            'data': {'fundamentals': [fact(value, '2025-07-01', '2026-06-30', id='corrected', version=version)]}}]},
            sources=[{'underlying_id': f'financial_fact:corrected:v{version}', 'evidence_ref': reference}]))
    section, = packet['sections'].values()
    item, = section['data']['sections'][0]['data']['fundamentals']
    assert item['value'] == '150'
    assert item['version'] == 2
    assert item['evidence_refs'] == ['E2']
    assert packet['sources'].keys() == {'E1', 'E2'}  # original sources remain auditable


def test_startup_preloads_embeddings_before_serving_without_model_calls(monkeypatch):
    import asyncio
    from app.main import app, lifespan
    from app.core.config import settings
    calls = []
    monkeypatch.setattr('app.ai.token_counting.local_assets', lambda: None)
    monkeypatch.setattr('app.services.rag_service.embed_text', lambda text: calls.append(('embedding', text)))
    monkeypatch.setattr(settings, 'auto_create_tables', False)
    async def idle():
        await asyncio.Event().wait()
    async def shutdown():
        calls.append(('shutdown', None))
    monkeypatch.setattr('app.services.assistant_execution.maintenance', idle)
    monkeypatch.setattr('app.services.assistant_execution.shutdown', shutdown)
    async def check():
        async with lifespan(app):
            assert calls == [('embedding', 'market financial evidence')]
            calls.append(('serving', None))
    asyncio.run(check())
    assert [kind for kind, _ in calls] == ['embedding', 'serving', 'shutdown']


def test_embedding_preload_failure_does_not_block_unrelated_api_and_does_not_log_secrets(monkeypatch, caplog):
    import asyncio
    from app.main import app, lifespan
    monkeypatch.setattr('app.ai.token_counting.local_assets', lambda: None)
    def unavailable(_):
        raise RuntimeError('sensitive failure text')
    async def idle():
        await asyncio.Event().wait()
    async def shutdown():
        pass
    monkeypatch.setattr('app.services.rag_service.embed_text', unavailable)
    monkeypatch.setattr('app.services.assistant_execution.maintenance', idle)
    monkeypatch.setattr('app.services.assistant_execution.shutdown', shutdown)
    async def check():
        async with lifespan(app):
            pass
    asyncio.run(check())
    assert 'RuntimeError' in caplog.text
    assert 'sensitive failure text' not in caplog.text
