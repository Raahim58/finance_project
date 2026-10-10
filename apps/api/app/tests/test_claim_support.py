from app.ai.tool_loop import _attach_evidence, citation_gate, resolve_citations
from app.tools.registry import tool_result


def evidence():
    checkpoint = {'evidence': {}, 'next_evidence': 1, 'resolved_identity': {
        'mentioned_instrument_candidates': [{'symbol': 'LUCK'}, {'symbol': 'FFC'}]}}
    _attach_evidence(checkpoint, tool_result('ok', {'financials': [
        {'metric': 'cash', 'value': '79770000000', 'unit': 'PKR', 'period_end': '2025-12-31',
         'accounting_basis': 'standalone', 'evidence_refs': ['cash']},
        {'metric': 'eps', 'value': '25', 'unit': 'PKR/share', 'period_end': '2025-12-31',
         'accounting_basis': 'standalone', 'evidence_refs': ['eps']} ]}, sources=[
        {'id': 'cash', 'underlying_id': 'financial_fact:cash:v1', 'symbol': 'FFC', 'title': 'Fixture FFC report'},
        {'id': 'eps', 'underlying_id': 'financial_fact:eps:v1', 'symbol': 'FFC', 'title': 'Fixture FFC report'}]), {'symbol': 'FFC'})
    return checkpoint


def test_wrong_issuer_is_rejected_even_when_marker_exists():
    cp = evidence()
    _, _, result = resolve_citations('LUCK announced a dividend. [[E1]]', cp)
    assert citation_gate(result, cp) == 'citation_support_invalid'
    assert result['support_errors'][0]['code'] == 'citation_issuer_mismatch'


def test_recorded_amount_keeps_units_and_source_scope():
    cp = evidence()
    answer, _, result = resolve_citations('FFC cash was {{fact:E1:cash:2025-12-31:standalone}}.', cp)
    assert '79770000000 PKR' in answer and 'standalone' in answer and '2025-12-31' in answer
    assert citation_gate(result, cp) is None


def test_scaled_rounding_is_supported_but_wrong_units_are_rejected():
    cp = evidence()
    _, _, result = resolve_citations('FFC cash was PKR 79.77 billion. [[E1]]', cp)
    assert citation_gate(result, cp) is None
    _, _, result = resolve_citations('FFC cash was PKR 79.77 million. [[E1]]', cp)
    assert citation_gate(result, cp) == 'citation_support_invalid'


def test_eps_reference_cannot_support_cash_amount_or_profit():
    cp = evidence()
    for text in ['FFC cash was PKR 25. [[E2]]', 'FFC profit was PKR 25. [[E2]]']:
        _, _, result = resolve_citations(text, cp)
        assert citation_gate(result, cp) == 'citation_support_invalid'


def test_conflicting_selector_fails_closed():
    cp = evidence()
    cp['evidence']['E1']['observations'].append({**cp['evidence']['E1']['observations'][0], 'value': '999'})
    _, _, result = resolve_citations('FFC cash was {{fact:E1:cash:2025-12-31:standalone}}.', cp)
    assert result['support_errors'][0]['code'] == 'financial_selector_unavailable'


def test_dividend_percentage_cannot_become_cash_per_share():
    cp = {'evidence': {}, 'next_evidence': 1}
    _attach_evidence(cp, tool_result('ok', {'corporate_actions': [
        {'type': 'cash_dividend_announced', 'source_backed': True, 'effective_date': '2026-10-01',
         'details': {'payout_percent': '250', 'cash_per_share': None}, 'evidence_refs': ['action']} ]},
        sources=[{'id': 'action', 'symbol': 'LUCK', 'title': 'Fixture payout announcement'}]), {'symbol': 'LUCK'})
    _, _, result = resolve_citations('LUCK dividend was 250%. [[E1]]', cp)
    assert citation_gate(result, cp) is None
    _, _, result = resolve_citations('LUCK dividend was PKR 25 per share. [[E1]]', cp)
    assert citation_gate(result, cp) == 'citation_support_invalid'
    _, _, result = resolve_citations('LUCK dividend yield was 250%. [[E1]]', cp)
    assert citation_gate(result, cp) == 'citation_support_invalid'


def test_narrative_entailment_is_not_mislabeled_as_verified():
    cp = evidence()
    _, _, result = resolve_citations('FFC will definitely recover. [[E1]]', cp)
    assert result['semantic_verification'] == 'not_performed'


def test_context_fact_id_binds_to_underlying_sql_record():
    cp = {'evidence': {}, 'next_evidence': 1}
    _attach_evidence(cp, tool_result('ok', {'fundamentals': [
        {'id': 'record-id', 'metric': 'cash', 'value': '12', 'unit': 'PKR'}]},
        sources=[{'underlying_id': 'financial_fact:record-id:v2', 'evidence_id': 'canonical-ref'}]))
    assert cp['evidence']['E1']['observations'][0]['value'] == '12'


def test_sql_dividend_statement_preserves_proposed_status_and_ignores_eps():
    cp = {'evidence': {}, 'next_evidence': 1}
    _attach_evidence(cp, tool_result('ok', {'evidence': [
        {'text': 'The Board proposed an interim dividend of Rs 14.50 per share; EPS was Rs 20 per share.',
         'kind': 'reported_fact', 'lifecycle': 'proposed', 'evidence_refs': ['statement']} ]},
         sources=[{'id': 'statement', 'symbol': 'FFC'}]), {'symbol': 'FFC'})
    assert [row['value'] for row in cp['evidence']['E1']['observations']] == ['14.50']
    _, _, result = resolve_citations('FFC proposed a dividend of Rs 14.50 per share. [[E1]]', cp)
    assert citation_gate(result, cp) is None
    _, _, result = resolve_citations('FFC paid a dividend of Rs 14.50 per share. [[E1]]', cp)
    assert citation_gate(result, cp) == 'citation_support_invalid'


def test_generic_concept_can_answer_without_fabricated_citations():
    cp = {'evidence': {}, 'routing': {'decision': {'primary': 'definition_or_concept'}}}
    _, _, result = resolve_citations('Dividend yield relates annual cash dividends to the share price.', cp)
    assert citation_gate(result, cp) is None
    _, _, result = resolve_citations('Unsupported source [[E1]].', cp)
    assert citation_gate(result, cp) == 'citation_reference_unknown'


def test_numbers_on_untyped_sources_are_flagged_not_rejected():
    cp = {'evidence': {}, 'next_evidence': 1, 'resolved_identity': {}}
    _attach_evidence(cp, tool_result('ok', {}, sources=[{'id': 'n1', 'title': 'News article'}]), {})
    _, _, result = resolve_citations('Cnergyico reported cash of Rs 18.30 on Jun 30, 2026. [[E1]]', cp)
    assert citation_gate(result, cp) is None
    assert result['unverified_number_lines'] == 1
    assert result['support_errors'] == []
