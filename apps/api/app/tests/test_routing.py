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
    assert names(plan) == ['research.morning_brief']


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
