"""Disposable PostgreSQL acceptance. Never runs against a canonical database.

Create an empty psx_phase11_test_* database first, then set DATABASE_URL to it.
Uses an encrypted fixture key and MockProvider; no external inference.
"""
import asyncio
import hashlib
import json
import multiprocessing
import os
import time
from sqlalchemy.engine import make_url


def queue_worker(identifier, output):
    from app.ai.providers.zai import credential_slot
    from app.services.assistant_diagnostics import execution_id
    async def run():
        token = execution_id.set(identifier)
        try:
            async with credential_slot("phase11-offline-coordination-fixture"):
                output.put("interactive" if identifier else "background")
                await asyncio.sleep(.2)
        finally:
            execution_id.reset(token)
    asyncio.run(run())


def main():
    url = make_url(os.environ["DATABASE_URL"])
    if url.drivername.split('+')[0] != 'postgresql' or not (url.database or '').startswith('psx_phase11_test_'):
        raise SystemExit('Refusing: DATABASE_URL must name a disposable psx_phase11_test_* PostgreSQL database')
    os.environ.update(APP_ENV='test', EMBEDDING_BACKEND='hash', SCHEDULED_RESEARCH_ENABLED='false', MARKET_HISTORY_BOOTSTRAP_ENABLED='false')
    from cryptography.fernet import Fernet
    os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
    from alembic import command
    from alembic.config import Config
    config = Config('alembic.ini')
    command.upgrade(config, 'head')
    from sqlalchemy import select, text
    from app.db.session import SessionLocal, engine
    from app.models.user import User, UserPreferences
    from app.models.llm_key import LLMApiKey
    from app.models.workstation import AssistantMessage
    from app.models.assistant_execution import AssistantExecution
    from app.models.assistant_workspace import ProviderQueueEntry
    from app.schemas.assistant import AssistantMessageCreate
    from app.core.security import encrypt_secret
    from app.services import assistant_execution, assistant_memory, assistant_events
    with SessionLocal.begin() as db:
        user=User(email='phase11-isolated@example.test',password_hash='unusable-offline-fixture')
        db.add(user);db.flush()
        db.add(UserPreferences(user_id=user.id,default_llm_provider='mock'))
        db.add(LLMApiKey(user_id=user.id,provider='mock',encrypted_api_key=encrypt_secret('mock-phase11-key'),masked_api_key='fixture',default_model='mock-psx-reasoner'))
        user_id=user.id
    with SessionLocal() as db:
        row=assistant_execution.accept(db,db.get(User,user_id),AssistantMessageCreate(question='Remember the explicit context requirements.'),'postgres-fixture')
        identifier,conversation_id=row.id,row.conversation_id
    asyncio.run(assistant_execution.execute(identifier))
    with SessionLocal() as db:
        row=db.get(AssistantExecution,identifier)
        assert row.status=='completed',row.error_code
        assert assistant_memory.search(db,user_id,conversation_id,'requirements')
        replay=assistant_events.replay(db,identifier)
        assert replay[-1]['kind']=='terminal'
        assert [e['sequence'] for e in replay]==list(range(1,len(replay)+1))
        assert len(list(db.scalars(select(AssistantMessage).where(AssistantMessage.conversation_id==conversation_id))))==2
    # Two independent processes contend behind an already-running credential lock.
    # Chat must start before the earlier waiting background request.
    credential=int.from_bytes(hashlib.sha256(b'phase11-offline-coordination-fixture').digest()[:8],signed=True)
    context=multiprocessing.get_context('spawn');output=context.Queue()
    processes=[]
    def wait_count(count):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            with SessionLocal() as db:
                if len(list(db.scalars(select(ProviderQueueEntry))))>=count:return
            time.sleep(.1)
        raise AssertionError('Provider queue did not register contenders')
    with engine.connect() as connection:
        connection.execute(text('SELECT pg_advisory_lock(:id)'),{'id':credential});connection.commit()
        try:
            background=context.Process(target=queue_worker,args=(None,output));background.start();processes.append(background);wait_count(1)
            interactive=context.Process(target=queue_worker,args=(identifier,output));interactive.start();processes.append(interactive);wait_count(2)
        finally:
            connection.execute(text('SELECT pg_advisory_unlock(:id)'),{'id':credential});connection.commit()
    order=[output.get(timeout=30),output.get(timeout=30)]
    for process in processes:
        process.join(timeout=10);assert process.exitcode==0
    assert order==['interactive','background'],order
    with SessionLocal() as db:assert db.scalar(select(ProviderQueueEntry)) is None
    command.downgrade(config,'0030_research_intelligence')
    command.upgrade(config,'head')
    print(json.dumps({'migration':'0031_assistant_workspace','mock_execution':'completed','encrypted_replay':'passed','postgres_text_search':'passed','cross_process_queue_order':order,'migration_round_trip':'passed'}))


if __name__=='__main__':main()
