"""Offline routing contracts: route labels, evidence contracts, budget, gaps."""
import pytest

from app.ai.company_packet import initial_calls, merge_result, model_packet, new_packet
from app.ai.routing import Route, RouterInput, plan_initial_evidence, route_query
from app.ai.routing.contracts import CONTRACTS
from app.ai.routing.planner import enforce_budget
from app.ai.routing.types import Block, PlanStep

LUCK = {'instrument_id': 'luck', 'symbol': 'LUCK'}
FFC = {'instrument_id': 'ffc', 'symbol': 'FFC'}
PORTFOLIO = {'portfolio_id': 'mine'}

from app.ai.routing.eval_cases import ROUTING_EVAL


@pytest.mark.parametrize('case', ROUTING_EVAL, ids=lambda c: c.id)
def test_rule_router_labels(case):
    decision = route_query(RouterInput(case.question, case.symbols, case.portfolio_selected))
    if case.id.startswith('vague-'):
        # Rules may not resolve these; they must flag them for the classifier instead of guessing.
        assert decision.tiebreak_candidates or decision.primary is case.primary
        return
    assert decision.primary is case.primary
    assert set(case.secondary) <= set(decision.secondary)
    assert len(decision.secondary) <= 2 and case.primary not in decision.secondary
    assert decision.fallback_used == (case.primary is Route.GENERAL_FALLBACK)


def test_routing_is_deterministic_and_company_only_never_routes_to_portfolio():
    first = route_query(RouterInput('How is my portfolio?', (), True))
    assert first == route_query(RouterInput('How is my portfolio?', (), True))
    decision = route_query(RouterInput('How is my portfolio?', (), True, company_only=True))
    assert decision.primary not in (Route.PORTFOLIO_REVIEW, Route.PORTFOLIO_IMPACT, Route.PORTFOLIO_REBALANCE)


def test_every_route_has_a_contract_without_overlap():
    assert set(CONTRACTS) == set(Route)
    for contract in CONTRACTS.values():
        assert not set(contract.required + contract.optional) & set(contract.forbidden)


def names(plan):
    return [c.name for c in plan.calls]


def test_market_brief_fetches_only_market_brief_even_with_selected_portfolio():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO}, "What's happening in the market today?", False, 12)
    assert names(plan) == ['market.overview', 'research.morning_brief']   # SQL numbers + commentary


def test_definition_fetches_nothing():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO}, 'What is a P/E ratio?', False, 12)
    assert plan.calls == [] and plan.decision.primary is Route.DEFINITION_OR_CONCEPT


def test_technical_setup_declares_missing_levels_instead_of_inventing_data():
    plan = plan_initial_evidence({'explicit_instrument': LUCK}, 'LUCK RSI and support?', True, 12)
    assert names(plan) == ['market.latest']
    assert {'block': 'technical_levels', 'reason': 'no_data_source'} in plan.missing_blocks


def test_portfolio_route_without_selected_portfolio_reports_gap():
    plan = plan_initial_evidence({}, 'What do you think of my portfolio?', False, 12)
    assert not any(c.name.startswith(('portfolio.', 'ips.', 'quant.')) for c in plan.calls)
    assert {'block': 'portfolio_snapshot', 'reason': 'no_portfolio_selected'} in plan.missing_blocks


def test_portfolio_review_caps_held_issuer_evidence_to_contract():
    held = [{'instrument_id': str(i), 'symbol': f'S{i}'} for i in range(8)]
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': held},
                                 'What do you think of my portfolio?', False, 32, use_digests=True)
    assert names(plan)[:3] == ['portfolio.summary', 'ips.compliance', 'quant.portfolio']
    assert names(plan).count('market.latest') == 3
    assert not any(c.name == 'research.morning_brief' for c in plan.calls)


def test_forbidden_blocks_are_never_planned_even_for_secondary_routes():
    plan = plan_initial_evidence({'explicit_instrument': LUCK}, 'LUCK RSI, merger and upgrade', True, 32)
    forbidden = set(CONTRACTS[plan.decision.primary].forbidden)
    assert not forbidden & {s.block for s in plan.steps}


def step(block, required, priority, tool='t'):
    return PlanStep(block, tool, {}, required, Route.GENERAL_FALLBACK, priority)


def test_budget_drops_optional_before_required_and_search_last():
    steps = [step(Block.PORTFOLIO_SNAPSHOT, True, 0), step(Block.EVENTS, False, 1),
             step(Block.EVIDENCE_SEARCH, True, 2), step(Block.SECTOR, False, 3, 'late')]
    kept, log = enforce_budget(steps, 2)
    assert [s.block for s in kept] == [Block.PORTFOLIO_SNAPSHOT, Block.EVIDENCE_SEARCH]
    assert [d['reason'] for d in log.dropped] == ['optional_over_cap'] * 2 and not log.missing_required
    kept, log = enforce_budget(steps, 1)
    assert [s.block for s in kept] == [Block.EVIDENCE_SEARCH]
    assert log.missing_required == ['portfolio_snapshot']
    assert enforce_budget(steps, 0)[0] == []


def test_tight_allowance_fails_closed_and_records_the_budget():
    plan = plan_initial_evidence({'explicit_instrument': LUCK}, 'Review LUCK', True, 4)
    assert plan.calls == [] and plan.budget.cap == 0
    assert initial_calls({'explicit_instrument': LUCK}, 'Review LUCK', True, 4) == []


def test_fallback_is_small_and_ambiguous_questions_do_not_fetch_dossiers():
    plan = plan_initial_evidence({'explicit_instrument': LUCK, 'portfolio': PORTFOLIO}, 'and?', False, 32, use_digests=True)
    assert plan.decision.fallback_used
    assert len(plan.calls) <= CONTRACTS[Route.GENERAL_FALLBACK].max_calls
    assert 'research.company_digest' not in names(plan)


def test_routing_record_is_inspectable_and_excludes_question_text():
    plan = plan_initial_evidence({'explicit_instrument': LUCK}, 'Review LUCK secret-phrase', True, 12)
    record = plan.to_record()
    assert record['decision']['primary'] and record['blocks'] and record['budget']['cap'] == 8
    assert 'secret-phrase' not in str(record)


def test_route_gaps_survive_packet_rebuilds_and_reach_the_model():
    from app.tools.registry import expand_model_data, tool_result
    from app.ai.providers.base import ContentBlock
    packet = new_packet({})
    packet['route_gaps'] = [{'block': 'technical_levels', 'reason': 'no_data_source', 'source': 'route_contract'}]
    merge_result(packet, ContentBlock('tool_call', id='1', name='market.latest', arguments={'instrument_id': 'luck'}),
                 tool_result('ok', {'value': '1'}))
    assert packet['missing_data'][0]['block'] == 'technical_levels'
    assert 'technical_levels' in str(expand_model_data(model_packet(packet)))


@pytest.mark.parametrize('question,executes_portfolio', [
    ("What's happening in the market today?", False),
    ('What is a P/E ratio?', False),
    ('Is LUCK RSI overbought, where is support?', False),
    ('What do you think of my portfolio right now?', True),
])
def test_executor_only_fetches_portfolio_when_the_route_allows_it(monkeypatch, question, executes_portfolio):
    """The preliminary scope fetch is executed, not just planned: check what actually runs."""
    import asyncio
    from types import SimpleNamespace
    from app.ai import tool_loop
    from app.tools.registry import tool_result
    executed = []

    async def fake_tool(_owner, call):
        executed.append(call.name)
        data = {'holdings': [{'instrument_id': 'luck', 'symbol': 'LUCK'}]} if call.name == 'portfolio.summary' else {}
        return tool_loop.ToolExecution(call, tool_result('ok', data), 1)
    monkeypatch.setattr(tool_loop, '_execute_tool', fake_tool)
    monkeypatch.setattr(tool_loop, '_save_checkpoint', lambda *_: None)
    identity = {'portfolio': PORTFOLIO}
    if 'LUCK' in question:
        identity['explicit_instrument'] = LUCK
    checkpoint = {'compact_evidence_enabled': True, 'resolved_identity': identity, 'evidence': {}, 'next_evidence': 1,
                  'tool_trace': [], 'reserved_tool_calls': 0, 'reserved_tool_call_ids': [], 'completed_tool_call_ids': [],
                  'turns': [tool_loop.ProviderTurn('system', [tool_loop.ContentBlock('text', text='Instructions')]).to_dict()]}
    asyncio.run(tool_loop._prepare_evidence('execution', 'owner', SimpleNamespace(question=question, company_only=False), checkpoint))
    assert ('portfolio.summary' in executed) is executes_portfolio
    if not executes_portfolio:
        assert not {'portfolio.summary', 'ips.compliance', 'quant.portfolio'} & set(executed)
        assert not checkpoint['evidence_packet'].get('portfolio_instruments')


def test_market_worded_question_keeps_the_market_brief_under_budget_pressure():
    held = [{'instrument_id': str(i), 'symbol': f'S{i}'} for i in range(5)]
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': held},
                                 "What’s happening in the market, and how does it affect me?", False, 11, use_digests=True)
    assert plan.decision.primary is Route.PORTFOLIO_IMPACT
    assert 'research.morning_brief' in names(plan)
    assert not plan.budget.missing_required


def test_goals_question_gets_performance_in_pass_one():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO}, 'Can my portfolio meet my goals?', False, 12)
    assert plan.decision.primary is Route.PORTFOLIO_REVIEW
    perf = next(s for s in plan.steps if s.tool == 'portfolio.performance')
    assert perf.required and perf.arguments == {'portfolio_id': 'mine', 'limit': 365}
    plain = plan_initial_evidence({'portfolio': PORTFOLIO}, 'What do you think of my portfolio?', False, 12)
    assert 'portfolio.performance' not in names(plain) or not next(
        s for s in plain.steps if s.tool == 'portfolio.performance').required


def test_buy_decision_gets_per_security_risk_in_pass_one():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'mentioned_instrument_candidates': [LUCK, FFC]},
                                 'Should I buy more LUCK or FFC?', False, 11)
    assert plan.decision.primary is Route.PORTFOLIO_REBALANCE
    assert names(plan).count('quant.security') == 2 and not plan.budget.missing_required


def test_market_questions_use_sql_snapshot_for_numbers_and_never_commentary_alone():
    for question in ("What's happening in the market today?", 'Why did the market fall?'):
        plan = plan_initial_evidence({}, question, False, 12)
        assert names(plan)[0] == 'market.overview', question


def test_market_plus_portfolio_question_has_snapshot_brief_and_portfolio_under_budget():
    held = [{'instrument_id': str(i), 'symbol': f'S{i}'} for i in range(5)]
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': held},
                                 "What’s happening in the market, and how does it affect me?", False, 11, use_digests=True)
    assert {'market.overview', 'research.morning_brief', 'ips.compliance'} <= set(names(plan))
    assert not plan.budget.missing_required


def test_performance_default_is_a_bounded_summary_with_correct_statistics():
    import json
    from datetime import date, timedelta
    from app.tools.portfolio_tools import summarize_performance
    twr = [0, 10, 20, 10, 5, 30]    # peak 1.20 -> trough 1.05 = -12.5%
    rows = []
    for i in range(365):
        value = twr[i % len(twr)] if i < 6 else 30 + i / 100
        rows.append({'value_date': str(date(2025, 1, 1) + timedelta(days=i)), 'total_value': str(1000 + i),
                     'external_cash_flow': '100' if i == 0 else '0', 'value_change': '1', 'day_change': '1',
                     'day_change_percent': '0.1', 'cumulative_twr_percent': str(value)})
    summary = summarize_performance(rows)
    assert summary['point_count'] == 365 and summary['max_drawdown_percent'] == '-12.5000'
    assert summary['max_drawdown_trough_date'] == '2025-01-05' and summary['net_external_cash_flow'] == '100'
    assert len(summary['sampled_points']) <= 25
    assert summary['sampled_points'][0] == rows[0] and summary['sampled_points'][-1] == rows[-1]
    assert len(json.dumps(summary)) < len(json.dumps(rows)) / 8   # was ~13.5k tokens for a year
    assert summarize_performance([])['point_count'] == 0


def test_digest_sections_follow_the_route_not_a_seven_section_default():
    held = [{'instrument_id': 'a', 'symbol': 'A'}, {'instrument_id': 'b', 'symbol': 'B'}]
    for question, limit in (('What do you think of my portfolio?', 2), ('Should I buy more A or B?', 3),
                            ("What’s happening in the market, and how does it affect me?", 3)):
        plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': held,
                                      'mentioned_instrument_candidates': held if 'buy' in question else []},
                                     question, False, 20, use_digests=True)
        digests = [s for s in plan.steps if s.tool == 'research.company_digest']
        assert digests and all(len(s.arguments['sections']) <= limit for s in digests), question
    full = plan_initial_evidence({'explicit_instrument': LUCK}, 'How are LUCK margins and debt?', True, 12, use_digests=True)
    assert len(next(s for s in full.steps if s.tool == 'research.company_digest').arguments['sections']) == 7


HOLDINGS = [{'instrument_id': f'h{i}', 'symbol': f'S{i}'} for i in range(9)]


def test_portfolio_wide_rebalance_loads_risk_for_every_holding_in_pass_one():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': HOLDINGS},
                                 'Are there better options than what I currently hold?', False, 32)
    assert plan.decision.primary is Route.PORTFOLIO_REBALANCE
    quant = [c for c in plan.calls if c.name == 'quant.securities']
    assert len(quant) == 1 and len(quant[0].arguments['instrument_ids']) == 9 and not plan.budget.missing_required
    # per-holding digests/prices are not fetched: portfolio.summary already carries prices
    assert 'research.company_digest' not in names(plan) and 'market.latest' not in names(plan)


def test_alternatives_question_screens_the_universe_excluding_holdings():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': HOLDINGS},
                                 'give options outside just my current portfolio holdings', False, 32)
    screen = [c for c in plan.calls if c.name == 'market.universe']
    assert len(screen) == 1
    args = screen[0].arguments
    assert args['rank_by'] == 'score' and set(args['exclude_instrument_ids']) == {h['instrument_id'] for h in HOLDINGS}
    assert not plan.budget.missing_required


def test_non_alternative_rebalance_does_not_screen_the_universe():
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': HOLDINGS},
                                 'Should I rebalance my portfolio?', False, 32)
    assert 'market.universe' not in names(plan)


@pytest.mark.parametrize('count', [5, 9])
@pytest.mark.parametrize('question', ['Are there better options than what I currently hold?',
                                    'Find alternatives outside my current holdings.',
                                    'Can you find stronger companies than the ones I own?',
                                    'Where should I redeploy my capital?'])
def test_alternatives_fit_actual_remaining_allowance(count, question):
    plan = plan_initial_evidence({'portfolio': PORTFOLIO, 'portfolio_instruments': HOLDINGS[:count]},
                                 question, False, 11, use_digests=True,
                                 completed_tools=('portfolio.summary',))
    assert 'portfolio.summary' not in names(plan)
    assert {'market.universe', 'quant.securities', 'ips.compliance', 'quant.portfolio'} <= set(names(plan))
    assert not plan.budget.missing_required and len(plan.calls) <= 7


def test_batch_quant_retains_missing_security_and_its_own_provenance(monkeypatch):
    from fastapi import HTTPException
    from app.tools import quant_tools
    from app.tools.registry import expand_model_data
    def calculate(_db, identifier):
        if identifier == 'absent':
            raise HTTPException(status_code=422, detail='Missing price history')
        return {'instrument_id': identifier, 'symbol': 'FIX', 'metrics': {'volatility': .2}}
    monkeypatch.setattr(quant_tools, 'security_quant', calculate)
    result = quant_tools._securities(None, None, quant_tools.SecuritiesInput(instrument_ids=['present', 'absent', 'present']))
    data = expand_model_data(result['data'])
    assert [row['status'] for row in data['securities']] == ['ok', 'missing']
    assert result['sources'][0]['instrument_id'] == 'present'


def test_actual_executor_keeps_screener_and_batch_coverage_under_default_limit(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.ai import tool_loop
    from app.tools.registry import tool_result
    monkeypatch.setattr(tool_loop.settings, 'assistant_max_tool_iterations', 12)
    monkeypatch.setattr(tool_loop, '_save_checkpoint', lambda *_: None)
    monkeypatch.setattr('app.ai.routing.persistence.record_routing', lambda *_: None)
    calls = []
    async def invoke(_owner, call):
        calls.append(call)
        data = {'holdings': HOLDINGS} if call.name == 'portfolio.summary' else {}
        return tool_loop.ToolExecution(call, tool_result('ok', data), 1)
    monkeypatch.setattr(tool_loop, '_execute_tool', invoke)
    cp = {'compact_evidence_enabled': True, 'resolved_identity': {'portfolio': PORTFOLIO},
          'evidence': {}, 'next_evidence': 1, 'tool_trace': [], 'reserved_tool_calls': 0,
          'reserved_tool_call_ids': [], 'completed_tool_call_ids': [],
          'turns': [tool_loop.ProviderTurn('system', [tool_loop.ContentBlock('text', text='Fixture')]).to_dict()]}
    asyncio.run(tool_loop._prepare_evidence('fixture', 'fixture',
        SimpleNamespace(question='Find alternatives outside my current holdings.', company_only=False), cp))
    assert [call.name for call in calls].count('portfolio.summary') == 1
    assert {'market.universe', 'quant.securities'} <= {call.name for call in calls}
    assert not cp['evidence_packet']['first_pass_unvisited_instruments']
    assert all('quant.securities' in cp['evidence_packet']['first_pass_coverage'][holding['instrument_id']] for holding in HOLDINGS)
    assert cp['reserved_tool_calls'] <= 8


def test_dividend_comparison_loads_payouts_without_security_quant():
    plan = plan_initial_evidence({'mentioned_instrument_candidates': [LUCK, FFC]},
        'Compare FFC and LUCK dividend payout records', True, 12, use_digests=True)
    assert plan.decision.primary is Route.FUNDAMENTALS_SNAPSHOT
    assert 'quant.security' not in names(plan)
    assert all(call.arguments['sections'] == ['dividends'] for call in plan.calls if call.name == 'research.company_digest')


def test_percentage_followup_uses_discussed_companies_and_dividend_reads():
    plan = plan_initial_evidence({'mentioned_instrument_candidates': [LUCK, FFC]},
        'wdym by 250%? what is the percentage against?', True, 12, use_digests=True)
    assert plan.decision.primary is Route.FUNDAMENTALS_SNAPSHOT
    assert all(call.arguments['sections'] == ['dividends'] for call in plan.calls if call.name == 'research.company_digest')
    from app.domain.evidence_query import dividend_query
    assert not dividend_query('What does 20% return against my benchmark mean?')


def test_model_typed_portfolio_id_is_replaced_by_the_selected_one():
    from app.ai.providers.base import ContentBlock
    from app.ai.tool_loop import _pin_selected_portfolio
    call = ContentBlock('tool_call', id='x', name='portfolio.summary', arguments={'portfolio_id': 'typo'})
    _pin_selected_portfolio(call, {'portfolio': {'portfolio_id': 'real'}})
    assert call.arguments['portfolio_id'] == 'real'
    other = ContentBlock('tool_call', id='y', name='market.latest', arguments={'instrument_id': 'i'})
    _pin_selected_portfolio(other, {'portfolio': {'portfolio_id': 'real'}})
    assert 'portfolio_id' not in other.arguments


@pytest.mark.usefixtures("database")
def test_universe_screen_ranks_by_score_screenable_only_and_excludes_held():
    import uuid
    from datetime import date
    from decimal import Decimal
    from app.db.session import SessionLocal
    from app.models.market import Company, Exchange
    from app.models.workstation import CompanyScreeningSnapshot, Instrument
    from app.tools.market_tools import MarketUniverseInput, _universe

    tag = uuid.uuid4().hex[:6].upper()
    with SessionLocal() as db:
        exchange = Exchange(code=f'X{tag}', name='Test exchange'); db.add(exchange); db.flush()
        made = {}
        for name, score, screenable in (('A', '0.9', True), ('B', '0.5', True), ('C', '0.99', False), ('D', '0.7', True)):
            company = Company(exchange_id=exchange.id, name=f'{tag}{name} Ltd', symbol=f'{tag}{name}', sector='Banks', is_active=True)
            db.add(company); db.flush()
            inst = Instrument(company_id=company.id, symbol=f'{tag}{name}', name=company.name,
                              instrument_type='equity', currency='PKR')
            db.add(inst); db.flush()
            db.add(CompanyScreeningSnapshot(instrument_id=inst.id, as_of_date=date(2026, 10, 1), sector='Banks',
                                            score=Decimal(score), completeness=Decimal('1'), screenable=screenable))
            made[name] = inst.id
        db.flush()
        out = _universe(db, None, MarketUniverseInput(
            sector='Banks', limit=10, rank_by='score', screening_fields=['score'],
            exclude_instrument_ids=[made['D']]))
        symbols = [row[1] for row in out['data']['rows'] if row[1].startswith(tag)]
        db.rollback()
    assert symbols == [f'{tag}A', f'{tag}B']


@pytest.mark.parametrize('question', ['what does my portfolio look like right now?', 'What do I hold?', 'how much is my portfolio worth'])
def test_simple_portfolio_questions_use_the_snapshot_only_route(question):
    decision = route_query(RouterInput(question, (), True))
    assert decision.primary is Route.PORTFOLIO_OVERVIEW
    plan = plan_initial_evidence({'portfolio': PORTFOLIO}, question, False, 12, decision=decision)
    assert [step.tool for step in plan.steps] == ['portfolio.summary']


@pytest.mark.parametrize('question', ['what are the risks in my portfolio?', 'how is my portfolio doing', 'should I rebalance my portfolio',
    'how will oil affect my portfolio'])
def test_analytical_portfolio_questions_keep_the_full_contract(question):
    assert route_query(RouterInput(question, (), True)).primary is not Route.PORTFOLIO_OVERVIEW
