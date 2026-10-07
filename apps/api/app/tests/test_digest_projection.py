from app.services.digest_projection import select_digest_evidence


def test_dividend_projection_preserves_original_units_and_prunes_unrelated_sources():
    snapshot = {'company': {'symbol': 'FIX'}, 'input_hash': 'fixture',
        'financials': [{'metric': 'revenue', 'value': '999', 'evidence_refs': ['revenue']},
                       {'metric': 'dividend_per_share', 'value': '1.25', 'unit': 'PKR/share',
                        'period_end': '2025-12-31', 'accounting_basis': 'standalone', 'evidence_refs': ['dividend']}],
        'corporate_actions': [{'type': 'cash_dividend', 'evidence_refs': ['dividend']},
                              {'type': 'stock_split', 'evidence_refs': ['split']}],
        'news': [{'text': 'The board declared a dividend, subject to approval.', 'evidence_refs': ['news']},
                 {'text': 'A capacity expansion was announced.', 'evidence_refs': ['expansion']}],
        'sources': {key: {'title': key} for key in ['revenue', 'dividend', 'split', 'news', 'expansion']}}
    result = select_digest_evidence(snapshot, ['dividends'])
    assert result['financials'] == [snapshot['financials'][1]]
    assert set(result['sources']) == {'dividend', 'news'}
    assert 'subject to approval' in result['news'][0]['text']
    assert len(snapshot['news']) == 2  # retained snapshot is untouched


def test_no_selection_preserves_full_snapshot_and_qualifications():
    snapshot = {'financials': [{'metric': 'revenue', 'unit': 'million'}], 'sources': {}}
    assert select_digest_evidence(snapshot, None) == snapshot


def test_snapshot_handler_honors_requested_sections(monkeypatch):
    from types import SimpleNamespace
    from app.core.config import settings
    from app.tools.research_tools import _company_digest, CompanyDigestInput
    from app.tools.registry import expand_model_data
    snapshot = {'input_hash': 'current', 'financials': [
        {'metric': 'revenue', 'value': '999', 'evidence_refs': ['revenue']}],
        'corporate_actions': [{'type': 'cash_dividend', 'evidence_refs': ['dividend']}],
        'news': [{'text': 'Capacity expansion was announced.', 'evidence_refs': ['expansion']}],
        'sources': {key: {'title': key} for key in ('revenue', 'dividend', 'expansion')}}
    monkeypatch.setattr(settings, 'pipeline_enabled', False)
    monkeypatch.setattr('app.services.company_digest_service.read_digest', lambda *_a, **_kw: {
        'snapshot': snapshot, 'input_hash': 'current', 'prepared_intelligence': [], 'brief_is_current': True})
    monkeypatch.setattr('app.services.pipeline.briefing.read', lambda *_a, **_kw: [])
    instrument = SimpleNamespace(id='fixture', symbol='FIX', sector='CEMENT')
    result = _company_digest(SimpleNamespace(get=lambda *_: instrument), None,
                             CompanyDigestInput(instrument_id='fixture', sections=['dividends']))
    data = expand_model_data(result['data'])
    assert data['financials'] == [] and data['news'] == []
    assert len(result['sources']) == 1 and result['sources'][0]['title'] == 'dividend'
    snapshot['corporate_actions'] = []
    missing = _company_digest(SimpleNamespace(get=lambda *_: instrument), None,
                              CompanyDigestInput(instrument_id='fixture', sections=['dividends']))
    assert missing['status'] == 'missing' and missing['sources'] == []
