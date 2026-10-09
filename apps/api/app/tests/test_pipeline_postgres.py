"""Optional PostgreSQL ledger/FTS integration in an isolated temporary schema.

PIPELINE_TEST_POSTGRES_URL must point at a disposable local Unix-socket server.
This test never migrates an application database or uses an LLM/queue broker.
"""
import importlib.util
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations


def migration(filename,connection):
    path=Path(__file__).resolve().parents[2]/'alembic/versions'/filename
    spec=importlib.util.spec_from_file_location(filename[:-3],path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.op=Operations(MigrationContext.configure(connection));return module


def test_postgres_ledger_and_weighted_text_index():
    url=os.getenv('PIPELINE_TEST_POSTGRES_URL')
    if not url: pytest.skip('Disposable PostgreSQL URL not supplied')
    parsed=make_url(url)
    if not str(parsed.query.get('host','')).startswith('/tmp/psx-pipeline-pg.'):
        pytest.fail('Refusing a non-disposable PostgreSQL test server')
    engine=create_engine(url)
    with engine.connect() as conn:
        transaction=conn.begin();schema='pipeline_test_'+uuid4().hex
        conn.execute(text(f'CREATE SCHEMA {schema}'))
        conn.execute(text(f'SET LOCAL search_path TO {schema}'))
        for table in ('data_sources','evidence_source_configs','instruments','source_artifacts','normalized_events','exchange_calendar_days'):
            conn.execute(text(f'CREATE TABLE {table}(id varchar(36) PRIMARY KEY)'))
        conn.execute(text('CREATE TABLE documents(id varchar(36) PRIMARY KEY,title text)'))
        conn.execute(text('CREATE TABLE document_chunks(id varchar(36) PRIMARY KEY,document_id varchar(36),section_title text,chunk_text text)'))
        first=migration('0034_pipeline_restoration.py',conn);first.upgrade()
        second=migration('0035_pipeline_text_index.py',conn);second.upgrade()
        conn.execute(text("INSERT INTO documents VALUES ('doc','Cement dividend')"))
        conn.execute(text("INSERT INTO document_chunks(id,document_id,chunk_text) VALUES ('chunk','doc','Reported expansion capacity')"))
        assert conn.scalar(text("SELECT count(*) FROM document_chunks WHERE search_vector @@ websearch_to_tsquery('english','dividend')"))==1
        conn.execute(text("UPDATE documents SET title='Gas tariff risk' WHERE id='doc'"))
        assert conn.scalar(text("SELECT count(*) FROM document_chunks WHERE search_vector @@ websearch_to_tsquery('english','dividend')"))==0
        assert conn.scalar(text("SELECT count(*) FROM document_chunks WHERE search_vector @@ websearch_to_tsquery('english','tariff')"))==1
        from app.services.pipeline import runs
        with Session(bind=conn,join_transaction_mode='create_savepoint') as db:
            row=runs.enqueue(db,'sections','document:doc',{'document_id':'doc'});db.commit()
            token=runs.claim(db,row.id);assert token
            assert runs.claim(db,row.id) is None
            runs.finish(db,row.id,token,{'ok':True},children=[('link','document:doc',{'document_id':'doc'})])
        second.downgrade();first.downgrade()
        transaction.rollback()
    engine.dispose()
