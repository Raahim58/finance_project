import hashlib
import json

import httpx
import pytest

from app.ai.company_packet import PACKET_PREFIX, initial_calls
from app.ai.token_counting import payload_breakdown
from app.ai.tool_loop import citation_failure_answer, citation_gate, resolve_citations

PROMPTS = [
    'What do you think of my portfolio right now?',
    'Should I buy more LUCK or FFC?',
    'Can my portfolio meet my goals?',
    'What’s happening in the market, and how does it affect me?',
    'Why has LUCK been moving lately?',
    'What could go wrong with my investments?',
    'Are there better options than what I currently hold?',
    'What about dividends?',
    'Does that change your view?',
    'Where did you get that number?',
]


@pytest.mark.parametrize('question', PROMPTS)
def test_selected_portfolio_and_ips_are_automatic_for_ordinary_questions(question):
    identity={'portfolio':{'portfolio_id':'owned-selection'}}
    calls=initial_calls(identity,question,False,32,use_digests=True)
    assert calls[0].name=='portfolio.summary'
    assert calls[1].name=='ips.compliance'
    assert all(c.arguments.get('portfolio_id')=='owned-selection'
               for c in calls if c.name in ('portfolio.summary','ips.compliance','quant.portfolio'))
    assert not any(c.arguments.get('portfolio_id') for c in initial_calls(identity,question,True,32))


@pytest.mark.parametrize('text,error', [
    ('Unsupported conclusion.', 'citation_missing'),
    ('Unknown [[E99]].', 'citation_reference_unknown'),
    ('Known [[E1]] and unknown [[E99]].', 'citation_reference_unknown'),
    ('Supported [[E1]].', None),
])
def test_presence_identity_gate_preserves_rejected_prose(text,error):
    checkpoint={'evidence':{'E1':{'source':{'title':'Fixture evidence','source_url':'https://example.test/original'}}}}
    _,_,outcome=resolve_citations(text,checkpoint)
    assert citation_gate(outcome,checkpoint)==error
    assert outcome['semantic_verification']=='not_performed'
    if error:
        fallback=citation_failure_answer(checkpoint)
        assert 'Unsupported conclusion' not in fallback
        # Rejected prose is never decorated with citations; sources stay in the source panel.
        assert '[[' not in fallback
        assert '1 evidence references are available in the source panel' in fallback


def test_packet_breakdown_is_measured_after_provider_assembly_and_not_additive():
    packet={'financials':{'columns':['value','unit','basis'],'rows':[['123.456000','PKR','standalone']]},
            'sources':{'E1':{'title':'اصل'}}}
    payload={'model':'fixture','messages':[{'role':'user','content':'What’s happening?\n'+PACKET_PREFIX+json.dumps(packet,ensure_ascii=False)}], 'tools':[]}
    result=payload_breakdown('zai',payload)
    assert result['component_estimates_additive'] is False
    assert result['evidence_packets'][0]['financials']['serialized_bytes']>0
    body=httpx.Request('POST','https://example.test',json=payload).content
    assert hashlib.sha256(body).hexdigest()!=hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    assert 'columns' in json.loads(body)['messages'][0]['content']


def test_gemini_interactions_fields_are_included_in_diagnostics():
    result=payload_breakdown('gemini',{'input':[{'type':'text','text':'Fixture'}],
        'system_instruction':'Fixture rules','generation_config':{'max_output_tokens':10}})
    assert set(result['components'])=={'input','system_instruction','generation_config'}
