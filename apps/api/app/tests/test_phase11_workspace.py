"""Offline acceptance of Phase 11 durability, ownership, memory and transports."""
import asyncio
import json
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.ai.providers.base import ProviderCallOptions, ProviderEvent, call_options, ContentBlock, ProviderTurn, ProviderTool, LLMProviderResult
from app.ai.providers.streaming import StreamAssembler, sse_json
from app.ai.providers.zai import ZaiProvider
from app.core.security import decrypt_secret, encrypt_secret
from app.db.session import SessionLocal
from app.models.user import User
from app.models.workstation import Conversation, AssistantMessage, Instrument
from app.models.assistant_execution import AssistantExecution, now
from app.models.assistant_workspace import ExecutionEvent, ConversationSummary
from app.schemas.assistant import AssistantMessageCreate, AssistantPageContext
from app.services import assistant_execution, assistant_events, assistant_memory, assistant_diagnostics
from app.services.assistant_policy import selected_policy
from app.core.config import settings


def signup(client, email="phase11@example.com"):
    response = client.post('/auth/signup', json={'email': email, 'password': 'password123'})
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def accepted(client, question="First question"):
    headers = signup(client)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == 'phase11@example.com'))
        run = assistant_execution.accept(db, user, AssistantMessageCreate(question=question), str(uuid4()))
        return headers, user.id, run.id, run.conversation_id


def test_snapshot_idempotency_and_active_conversation(client):
    headers, user_id, identifier, conversation_id = accepted(client)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        row = db.get(AssistantExecution, identifier)
        policy = json.loads(row.policy_json)
        assert policy['input'] == 48000 and policy['history'] == 24000
        original = db.scalar(select(AssistantMessage).where(AssistantMessage.execution_id == identifier))
        assert json.loads(original.context_json)['page'] == 'workspace'
        with pytest.raises(Exception) as exc:
            assistant_execution.accept(db, user, AssistantMessageCreate(question='Second'), 'another', conversation_id)
        assert exc.value.status_code == 409
    assert client.post(f'/assistant/runs/{identifier}/cancel',headers=headers).json()['status']=='stopped'
    assert client.post(f'/assistant/runs/{identifier}/cancel',headers=headers).json()['status']=='stopped'
    with SessionLocal() as db:
        assert len(list(db.scalars(select(ExecutionEvent).where(ExecutionEvent.kind=='terminal')))) == 1


def test_context_changes_apply_only_to_subsequent_messages(client):
    headers, user_id, identifier, conversation_id = accepted(client)
    with SessionLocal.begin() as db:
        db.get(AssistantExecution, identifier).status='completed'
        db.add_all([Instrument(id='ogdc',symbol='OGDC',name='Oil and Gas'),Instrument(id='luck',symbol='LUCK',name='Lucky')])
    for company in ['ogdc','luck']:
        with SessionLocal() as db:
            row=assistant_execution.accept(db,db.get(User,user_id),AssistantMessageCreate(question=company,
                page_context=AssistantPageContext(page='company',instrument_id=company)),str(uuid4()),conversation_id)
            row.status='completed';db.commit()
    history=client.get(f'/assistant/workspace/conversations/{conversation_id}/messages',headers=headers).json()
    assert [m['context'].get('symbol') for m in history['items']]==[None,'OGDC','LUCK']


def test_replay_encryption_pagination_and_ownership(client):
    headers,user_id,identifier,conversation_id=accepted(client)
    stranger=signup(client,'stranger11@example.com')
    assistant_events.append(identifier,'text_delta',{'text':'First '})
    assistant_events.append(identifier,'text_delta',{'text':'second'})
    with SessionLocal.begin() as db:
        row=db.get(AssistantExecution,identifier);row.status='interrupted';row.completed_at=now()
        events=assistant_events.replay(db,identifier,1)
        assert events[0]['sequence']==2 and events[0]['payload']['text']=='second'
        encrypted=db.scalar(select(ExecutionEvent).where(ExecutionEvent.sequence==1))
        assert 'First' not in encrypted.payload_encrypted
    for path in [f'/assistant/runs/{identifier}/events',f'/assistant/workspace/conversations/{conversation_id}/messages',f'/assistant/workspace/conversations/{conversation_id}/search']:
        assert client.get(path,headers=stranger).status_code==404
    assert client.post(f'/assistant/runs/{identifier}/cancel',headers=stranger).status_code==404
    assert client.post(f'/assistant/workspace/conversations/{conversation_id}/retry-summary',headers=stranger).status_code==404
    page=client.get('/assistant/workspace/conversations?limit=1',headers=headers).json()
    assert page['items'][0]['id']==conversation_id
    replay=client.get(f'/assistant/runs/{identifier}/events?after=1',headers=headers).text
    assert 'First ' not in replay and 'second' in replay and 'interrupted' in replay
    with SessionLocal.begin() as db:
        db.get(AssistantExecution,identifier).completed_at=now()-timedelta(hours=25)
    with SessionLocal.begin() as db:assistant_events.prune(db)
    with SessionLocal() as db:
        assert db.scalar(select(ExecutionEvent)) is None
        assert db.scalar(select(AssistantMessage)) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['zai','openai','openrouter'])
async def test_native_fragmented_openai_stream_never_emits_reasoning(provider):
    visible=[]
    async def event(value):visible.append(value)
    token=call_options.set(ProviderCallOptions(on_event=event))
    try:
        assembler=StreamAssembler(provider)
        for delta in [{'reasoning_content':'private thought'},{'content':'Hello '},{'content':'world'},
                      {'tool_calls':[{'index':0,'id':'call1','function':{'name':'market__prices','arguments':'{"sym'}}]},
                      {'tool_calls':[{'index':0,'function':{'arguments':'bol":"OGDC"}'}}]}]:
            await assembler.feed({'choices':[{'delta':delta}]})
        await assembler.feed({'choices':[{'delta':{},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':12,'completion_tokens':8}})
        data=assembler.result()
        assert ''.join(e.text for e in visible)=='Hello world'
        assert data['choices'][0]['message']['reasoning_content']=='private thought'
        assert json.loads(data['choices'][0]['message']['tool_calls'][0]['function']['arguments'])=={'symbol':'OGDC'}
        assert data['usage']['completion_tokens']==8
    finally:call_options.reset(token)


@pytest.mark.asyncio
async def test_anthropic_thinking_signature_and_fragmented_arguments():
    assembler=StreamAssembler('anthropic')
    events=[{'type':'message_start','message':{'id':'m','usage':{'input_tokens':10}}},
        {'type':'content_block_start','index':0,'content_block':{'type':'thinking','thinking':'','signature':''}},
        {'type':'content_block_delta','index':0,'delta':{'type':'thinking_delta','thinking':'secret'}},
        {'type':'content_block_delta','index':0,'delta':{'type':'signature_delta','signature':'signature'}},
        {'type':'content_block_start','index':1,'content_block':{'type':'tool_use','id':'t','name':'market__prices','input':{}}},
        {'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'{"symbol":'}},
        {'type':'content_block_delta','index':1,'delta':{'type':'input_json_delta','partial_json':'"LUCK"}'}},
        {'type':'message_delta','delta':{'stop_reason':'tool_use'},'usage':{'output_tokens':9}}, {'type':'message_stop'}]
    for event in events:await assembler.feed(event)
    data=assembler.result()
    assert data['content'][0]['signature']=='signature'
    assert data['content'][1]['input']=={'symbol':'LUCK'}
    assert data['usage']=={'input_tokens':10,'output_tokens':9}


@pytest.mark.asyncio
async def test_gemini_stream_preserves_id_and_arguments():
    assembler=StreamAssembler('gemini')
    for event in [{'event_type':'interaction.created','interaction':{'id':'continuation'}},
        {'event_type':'step.start','index':0,'step':{'type':'function_call','id':'call','name':'market__freshness','arguments':{}}},
        {'event_type':'step.delta','index':0,'delta':{'type':'arguments_delta','arguments_delta':'{"limit":'}},
        {'event_type':'step.delta','index':0,'delta':{'type':'arguments_delta','arguments_delta':'2}'}},
        {'event_type':'interaction.completed','interaction':{'status':'requires_action','usage':{'total_input_tokens':42}}}]:
        await assembler.feed(event)
    result=assembler.result()
    assert result['id']=='continuation' and result['steps'][0]['arguments']=={'limit':2}


@pytest.mark.asyncio
async def test_compaction_failure_suppression_and_version_boundaries(client,monkeypatch):
    _,user_id,identifier,conversation_id=accepted(client)
    policy=selected_policy()|{'history':1300,'recent':1000,'summary':100,'input':4000}
    monkeypatch.setattr(assistant_memory,'execution_policy',lambda:policy)
    with SessionLocal.begin() as db:
        for index in range(8):db.add(AssistantMessage(conversation_id=conversation_id,role='user',content='Earlier requirement '+str(index)+' detail '*10))
    with SessionLocal() as db:
        _, history_rows = assistant_memory.retained_history(db, conversation_id, identifier)
        from app.reasoning.projection import estimate_tokens
        size = estimate_tokens(["", *[assistant_memory.message_record(r) for r in history_rows]])
        policy["history"] = size - 1
        policy["recent"] = size * 3 // 4
    class Provider:
        calls=0
        async def chat_with_options(self,*args,**kwargs):
            self.calls+=1;raise RuntimeError('offline failure')
    provider=Provider()
    await assistant_memory.prepare(identifier,user_id,conversation_id,provider,'fixture','test')
    await assistant_memory.prepare(identifier,user_id,conversation_id,provider,'fixture','test')
    assert provider.calls==1
    with SessionLocal.begin() as db:
        db.get(Conversation,conversation_id).summary_failure=None
    async def success(*args,**kwargs):
        assert kwargs['options'].thinking is False
        return LLMProviderResult(content='Keep requirements and OGDC context dated.',provider='mock',model='mock',input_tokens=100,output_tokens=12)
    provider.chat_with_options=success
    await assistant_memory.prepare(identifier,user_id,conversation_id,provider,'fixture','test')
    with SessionLocal() as db:
        summaries=list(db.scalars(select(ConversationSummary)))
        assert len(summaries)==1 and summaries[0].covered_through_message_id
        assert len(list(db.scalars(select(AssistantMessage))))==9
        assert db.get(Conversation,conversation_id).summary_failure is None
        assert len(json.loads(db.get(AssistantExecution,identifier).accounting_json)['summaries'])==2


def test_trial_selection_is_explicit_and_excludes_reasoning(monkeypatch):
    first=selected_policy();monkeypatch.setattr(settings,'assistant_token_trial','trial2');second=selected_policy()
    assert first['history']==24000 and second['history']==64000
    assert second['cumulative_input']==first['cumulative_input']==180000
    assert first['calls']==second['calls']==6


@pytest.mark.asyncio
async def test_native_http_sse_stream_and_zai_thinking_continuation(monkeypatch):
    import httpx
    from app.ai.providers import http_placeholders
    original_client=httpx.AsyncClient
    requests=[]
    lines=[{'choices':[{'delta':{'reasoning_content':'opaque thought'}}]},
           {'choices':[{'delta':{'content':'Live '}}]}, {'choices':[{'delta':{'content':'text'}}]},
           {'choices':[{'delta':{},'finish_reason':'stop'}]}, {'choices':[],'usage':{'prompt_tokens':40,'completion_tokens':20}}]
    def handler(request):
        requests.append(json.loads(request.content))
        wire=''.join('data: '+json.dumps(line)+'\n\n' for line in lines)+'data: [DONE]\n\n'
        return httpx.Response(200,text=wire,headers={'content-type':'text/event-stream'})
    monkeypatch.setattr(http_placeholders.httpx,'AsyncClient',lambda **kwargs:original_client(transport=httpx.MockTransport(handler),**kwargs))
    provider=ZaiProvider();tools=[ProviderTool('market.prices','Prices',{'type':'object'})]
    previous=ProviderTurn('assistant',[ContentBlock('tool_call',id='call',name='market.prices',arguments={})],{'reasoning_content':'previous opaque thought'})
    turns=[ProviderTurn('user',[ContentBlock('text',text='Price?')]),previous,ProviderTurn('user',[ContentBlock('tool_result',id='call',name='market.prices',result={'status':'missing'})])]
    events=[event async for event in provider.stream_tool_chat('offline-fixture-key',turns,tools,options=ProviderCallOptions(thinking=True,max_output_tokens=8192))]
    assert ''.join(e.text for e in events if e.kind=='text_delta')=='Live text'
    assert requests[0]['stream'] is True and requests[0]['thinking']=={'type':'enabled','clear_thinking':False}
    assert requests[0]['messages'][1]['reasoning_content']=='previous opaque thought'
    assert requests[0]['messages'][2]['tool_call_id']=='call'
    completed=next(e.result for e in events if e.kind=='completion')
    assert completed.turn.opaque['reasoning_content']=='opaque thought'
    assert completed.input_tokens==40 and completed.output_tokens==20


def test_budget_enforced_at_actual_request_boundary(client,monkeypatch):
    from app.tests.test_phase8_phase2_tool_loop import _auth_with_anthropic
    from app.ai.providers.http_placeholders import AnthropicProvider
    from app.services import assistant_policy
    headers,_=_auth_with_anthropic(client,monkeypatch,email='budget11@example.com')
    provider=AnthropicProvider();requests=[]
    async def post(url,key,payload):
        requests.append(payload)
        return {'id':'budget-call','model':'claude-test','stop_reason':'tool_use',
                'content':[{'type':'tool_use','id':f'tool{len(requests)}','name':'market__freshness','input':{}}],
                'usage':{'input_tokens':40000,'output_tokens':100}}
    monkeypatch.setattr(provider,'_post',post);monkeypatch.setattr('app.ai.tool_loop.get_provider',lambda _:provider)
    policy=assistant_policy.selected_policy()|{'cumulative_input':45000}
    monkeypatch.setattr(assistant_policy,'selected_policy',lambda:policy)
    response=client.post('/assistant/messages',headers=headers,json={'question':'Inspect evidence','provider':'anthropic'})
    assert response.status_code==201
    assert len(requests)==1
    assert response.json()['synthesis']['generation']['error_code']=='question_budget_exhausted'
    assert requests[0]['max_tokens']==8192
    assert requests[0]['thinking']=={'type':'adaptive'}


@pytest.mark.asyncio
async def test_stream_chunks_batch_and_terminal_partial_survives_pruning(client):
    headers,_,identifier,conversation_id=accepted(client)
    batch=assistant_events.StreamBatch(identifier)
    await batch(ProviderEvent('text_delta',text='Partial text'))
    await asyncio.sleep(.3)
    with SessionLocal() as db:
        assert len(assistant_events.replay(db,identifier))==1
    with SessionLocal() as db:assistant_execution.cancel(db,db.get(AssistantExecution,identifier).user_id,identifier)
    batch.close()
    with SessionLocal.begin() as db:
        row=db.get(AssistantExecution,identifier);row.completed_at=now()-timedelta(hours=25)
    with SessionLocal.begin() as db:assistant_events.prune(db)
    history=client.get(f'/assistant/workspace/conversations/{conversation_id}/messages',headers=headers).json()
    assert history['items'][-1]['content']=='Partial text' and history['items'][-1]['outcome']=='stopped'


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['zai', 'anthropic', 'gemini'])
async def test_truncated_tool_arguments_are_incomplete_without_execution(provider):
    assembler = StreamAssembler(provider)
    if provider == 'zai':
        await assembler.feed({'choices': [{'delta': {'content': 'Partial', 'tool_calls': [
            {'index': 0, 'id': 't', 'function': {'name': 'read', 'arguments': '{"x":'}}]}, 'finish_reason': 'length'}]})
        result = assembler.result()
        assert result['choices'][0]['finish_reason'] == 'length'
        assert not result['choices'][0]['message'].get('tool_calls')
    elif provider == 'anthropic':
        await assembler.feed({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'tool_use', 'id': 't', 'name': 'read'}})
        await assembler.feed({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': '{"x":'}})
        await assembler.feed({'type': 'message_delta', 'delta': {'stop_reason': 'max_tokens'}})
        await assembler.feed({'type': 'message_stop'})
        result = assembler.result()
        assert result['stop_reason'] == 'max_tokens' and result['content'] == []
    else:
        await assembler.feed({'event_type': 'step.start', 'index': 0, 'step': {'type': 'function_call', 'id': 't'}})
        await assembler.feed({'event_type': 'step.delta', 'index': 0, 'delta': {'arguments_delta': '{"x":'}})
        result = assembler.result()
        assert result['status'] == 'incomplete' and not result.get('steps')


def test_duplicate_evidence_projection_preserves_originals_and_arguments():
    from app.ai.tool_loop import _deduplicate_tool_evidence
    evidence = {'source_id': 'source1', 'record': 'x' * 400}
    turns = [ProviderTurn('user', [ContentBlock('tool_result', id='first', result=evidence),
                                ContentBlock('tool_result', id='second', result=evidence)])]
    projected = _deduplicate_tool_evidence(turns)
    assert projected[0].content[0].result == evidence
    assert projected[0].content[1].result['duplicate_of_tool_call_id'] == 'first'
    assert turns[0].content[1].result == evidence


@pytest.mark.asyncio
async def test_execution_slot_timeout_has_distinct_durable_outcome(client, monkeypatch):
    _, _, identifier, _ = accepted(client)
    monkeypatch.setattr(assistant_execution, '_slots', asyncio.Semaphore(0))
    monkeypatch.setattr(settings, 'assistant_queue_timeout_seconds', .01)
    await assistant_execution.execute(identifier)
    with SessionLocal() as db:
        row = db.get(AssistantExecution, identifier)
        assert row.status == 'timeout' and row.error_code == 'execution_queue_timeout'
        assert assistant_events.replay(db, identifier)[-1]['payload']['status'] == 'timeout'


@pytest.mark.asyncio
async def test_committed_response_checkpoint_gap_reuses_response_without_model(client):
    from app.ai.tool_loop import _provider_turn
    _, _, identifier, _ = accepted(client)
    token = assistant_diagnostics.execution_id.set(identifier)
    try:
        record = [{'role': 'user', 'content': '{"messages": "exact serialized input"}'}]
        attempt = assistant_diagnostics.begin_attempt('tool_loop_turn', 'zai', 'glm-4.7-flash', record, 12)
        assistant_diagnostics.finish_attempt(attempt, response=LLMProviderResult(
            content='Already paid for and complete', provider='zai', model='glm-4.7-flash',
            input_tokens=12, output_tokens=7, finish_reason='stop',
            turn=ProviderTurn('assistant', [ContentBlock('text', text='Already paid for and complete')])), latency_ms=10)
        class Provider:
            name = 'zai'
            default_model = 'glm-4.7-flash'
            async def tool_chat_with_options(self, *args, **kwargs):
                raise AssertionError('Recovery must not call a model')
        result = await _provider_turn(Provider(), 'offline-fixture', None, [], [])
        assert result.content == 'Already paid for and complete' and result.output_tokens == 7
    finally:
        assistant_diagnostics.execution_id.reset(token)
