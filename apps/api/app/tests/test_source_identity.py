import copy

import pytest

from app.ai.source_identity import source_identity
from app.ai.tool_loop import _attach_evidence
from app.tools.portfolio_tools import portfolio_source


def portfolio_evidence(method='stored_holdings_and_database_prices', cutoff='2026-10-01'):
    return portfolio_source('owned-portfolio', {'data_cutoff': cutoff}, method)


@pytest.mark.parametrize('change', [
    {'record_id': 'another-owned-portfolio'},
    {'calculation_method': 'ledger_time_weighted_return'},
    {'calculation_method': 'aligned_price_covariance_and_ledger_performance'},
    {'data_cutoff': '2026-10-02'},
    {'run_id': 'different-stored-run'},
    {'price_provenance': [{'symbol': 'FIXTURE', 'artifact_id': 'corrected-artifact'}]},
])
def test_distinct_internal_sql_evidence_has_distinct_identity(change):
    original = portfolio_evidence()
    assert source_identity(original) != source_identity(original | change)


def test_internal_record_identity_is_stable_across_presentation_changes():
    original = portfolio_evidence()
    presented = original | {'source_name': 'Portfolio evidence', 'title': 'A display title',
                            'id': 'presentation-local-id', 'evidence_ref': 'E99'}
    assert source_identity(original) == source_identity(presented)
    assert source_identity(original) == source_identity(dict(reversed(list(original.items()))))


def test_internal_sources_do_not_overwrite_earlier_calculation_citations():
    checkpoint = {'evidence': {}, 'next_evidence': 1}
    summary = portfolio_evidence()
    performance = portfolio_evidence('ledger_time_weighted_return', '2026-10-02')
    quant = portfolio_evidence('aligned_price_covariance_and_ledger_performance')
    original = copy.deepcopy([summary, performance, quant])

    attached = _attach_evidence(checkpoint, {'sources': [summary, performance, quant]})

    assert [source['evidence_ref'] for source in attached['sources']] == ['E1', 'E2', 'E3']
    assert [item['source'] for item in checkpoint['evidence'].values()] == original
    repeated = _attach_evidence(checkpoint, {'sources': [summary]})
    assert repeated['sources'][0]['evidence_ref'] == 'E1'
    assert checkpoint['next_evidence'] == 4


@pytest.mark.parametrize('change', [
    {'record_id': 'other-ips-version'}, {'portfolio_id': 'another-owned-portfolio'},
    {'version': 2}, {'confirmed_at': '2026-10-02T00:00:00+00:00'},
])
def test_ips_citations_preserve_selected_version_and_confirmation(change):
    source = {'record_type': 'ips_version', 'record_id': 'selected-ips-version',
              'portfolio_id': 'owned-portfolio', 'version': 1,
              'confirmed_at': '2026-10-01T00:00:00+00:00',
              'calculation_method': 'evaluate_ips_constraints'}
    assert source_identity(source) != source_identity(source | change)


def test_missing_ips_version_remains_scoped_to_its_portfolio():
    source = {'record_type': 'ips_version', 'record_id': None,
              'portfolio_id': 'owned-portfolio', 'calculation_method': 'evaluate_ips_constraints'}
    assert source_identity(source) != source_identity(source | {'portfolio_id': 'another-owned-portfolio'})


def test_verification_and_security_calculations_do_not_collapse_by_label():
    verification = {'source_name': 'Server allocation verification',
                    'portfolio_id': 'owned-portfolio', 'verification_id': 'first-verification',
                    'calculation_method': 'gross_cash_lot_rounding_and_ips_comparison'}
    assert source_identity(verification) != source_identity(
        verification | {'verification_id': 'revised-verification'})
    security = {'source_name': 'Canonical security price risk calculation',
                'instrument_id': 'fixture-security-a', 'data_cutoff': '2026-10-01',
                'calculation_method': 'daily_price_returns_risk_metrics'}
    assert source_identity(security) != source_identity(security | {'instrument_id': 'fixture-security-b'})
    assert source_identity(security) != source_identity(security | {'data_cutoff': '2026-10-02'})


def test_document_and_chunk_identity_keeps_existing_span_semantics():
    source = {'document_id': 'filing', 'page_number': 7, 'quote_snippet': 'A supplied source span.'}
    assert source_identity(source) == source_identity(source | {'title': 'Changed display title'})
    assert source_identity(source) != source_identity(source | {'quote_snippet': 'A distinct source span.'})
    assert source_identity(source) != source_identity(source | {'page_number': 8})
    chunk = source | {'chunk_id': 'original-chunk'}
    assert source_identity(chunk) == source_identity(chunk | {'title': 'Changed display title'})
    assert source_identity(chunk) != source_identity(chunk | {'chunk_id': 'another-chunk'})
