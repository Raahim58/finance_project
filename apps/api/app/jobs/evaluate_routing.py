"""Evaluate the router (and optionally the live tie-break classifier) on the eval set.

  python -m app.jobs.evaluate_routing                       # rules only, offline
  ZAI_API_KEY=... python -m app.jobs.evaluate_routing --live --provider zai \
      --model glm-4.5-flash --output /tmp/routing-live.jsonl [--persist]

The key is read from the named environment variable at call time and never
printed or stored. --persist writes routing_eval_runs rows (needs migrations).
"""
import argparse
import asyncio
import json
import os
import time
from uuid import uuid4

from app.ai.providers.base import ProviderCallOptions
from app.ai.providers.registry import get_provider
from app.ai.routing.classifier import apply_tie_break, tie_break
from app.ai.routing.eval_cases import ROUTING_EVAL
from app.ai.routing.planner import rule_decision
from app.ai.routing.rules import route_query
from app.ai.routing.types import RouterInput


def _identity(case):
    entities = [{'instrument_id': s.lower(), 'symbol': s} for s in case.symbols]
    return {'mentioned_instrument_candidates': entities,
            'portfolio': {'portfolio_id': 'eval'} if case.portfolio_selected else None}


async def run(args):
    provider = api_key = None
    if args.live:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f'{args.api_key_env} is not set')
        provider = get_provider(args.provider)
    run_id = str(uuid4())
    rows = []
    for case in ROUTING_EVAL:
        rules = route_query(RouterInput(case.question, case.symbols, case.portfolio_selected))
        decision, usage, latency, outcome = rules, {}, None, 'not_needed'

        async def complete(system, user):
            nonlocal usage, latency
            started = time.perf_counter()
            result = await provider.chat_with_options(
                api_key, [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
                args.model, options=ProviderCallOptions(thinking=False, max_output_tokens=300, deadline_seconds=90))
            latency = round((time.perf_counter() - started) * 1000)
            usage = {'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens}
            return result.content

        if args.live:
            tb = await tie_break(rules, case.question, complete)
            decision, outcome = apply_tie_break(rules, tb), tb.outcome
            if tb.outcome == 'provider_error':
                await asyncio.sleep(2)
        errors = []
        if decision.primary is not case.primary:
            errors.append(f'primary {decision.primary.value} != {case.primary.value}')
        missing = [r.value for r in case.secondary if r not in decision.secondary]
        if missing:
            errors.append(f'missing secondary {missing}')
        rows.append({'case': case.id, 'expected': case.primary.value, 'rules': rules.primary.value,
                     'actual': decision.primary.value, 'source': decision.decision_source,
                     'tiebreak_candidates': len(rules.tiebreak_candidates), 'classifier_outcome': outcome,
                     'matched': not errors, 'rules_matched': rules.primary is case.primary, 'errors': errors,
                     'latency_ms': latency, **usage})
    if args.persist:
        from app.db.session import SessionLocal
        from app.models.routing import RoutingEvalRun
        with SessionLocal.begin() as db:
            for row, case in zip(rows, ROUTING_EVAL):
                db.add(RoutingEvalRun(
                    run_id=run_id, eval_case_id=case.id, router_version=decision.router_version,
                    mode='rules_plus_classifier' if args.live else 'rules',
                    provider=args.provider if args.live else None, model=args.model if args.live else None,
                    expected_primary=case.primary.value, actual_primary=row['actual'],
                    expected_secondary_json=json.dumps([r.value for r in case.secondary]),
                    actual_secondary_json='[]', decision_source=row['source'],
                    matched=row['matched'], errors_json=json.dumps(row['errors'])))
    if args.output:
        with open(args.output, 'w') as handle:
            for row in rows:
                handle.write(json.dumps({'run_id': run_id, 'model': args.model if args.live else None, **row}) + '\n')
    total = len(rows)
    print(f'cases={total} rules_matched={sum(r["rules_matched"] for r in rows)} '
          f'final_matched={sum(r["matched"] for r in rows)} '
          f'classifier_calls={sum(r["classifier_outcome"] != "not_needed" for r in rows)}')
    for row in rows:
        if not row['matched'] or row['classifier_outcome'] != 'not_needed':
            print(row)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--provider', default='zai')
    parser.add_argument('--model', default='glm-4.5-flash')
    parser.add_argument('--api-key-env', default='ZAI_API_KEY')
    parser.add_argument('--output')
    parser.add_argument('--persist', action='store_true')
    asyncio.run(run(parser.parse_args()))
