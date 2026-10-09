"""Deploy must work while ingestion runs: never stop workers as a group, never apply a
breaking migration under old-code workers, roll workers one at a time afterward."""
import os
import subprocess
from pathlib import Path

import pytest

from app.jobs.check_migrations_additive import breaking_ops, load_script, pending_breaking

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'ops' / 'oracle-deploy'
RUNNING = ['worker-evidence-fetch', 'pipeline-fetch', 'pipeline-parse', 'pipeline-scheduler', 'evidence-scheduler']


def test_additive_migrations_pass_and_destructive_ones_are_flagged():
    assert breaking_ops("def upgrade():\n    op.create_table('t')\n    op.add_column('t', c)\n    op.create_index('i','t',['a'])\n") == []
    assert breaking_ops("def upgrade():\n    op.drop_column('t','c')\n") == ['drop_column']
    assert breaking_ops("def upgrade():\n    op.alter_column('t','c', type_=x)\n    op.rename_table('a','b')\n") == ['alter_column', 'rename_table']
    flagged = breaking_ops("def upgrade():\n    op.execute('DROP TABLE x')\n")
    assert len(flagged) == 1 and flagged[0].startswith("execute")
    assert breaking_ops("def upgrade():\n    op.create_table('t')\n\ndef downgrade():\n    op.drop_table('t')\n") == []


def test_this_branch_routing_migration_is_additive_on_top_of_production_revision():
    script = load_script()
    assert pending_breaking(script, '0035_pipeline_text_index') == []


@pytest.fixture
def stub(tmp_path):
    """Stub external commands so rollout contracts also run on hosts without flock."""
    bindir, log = tmp_path / 'bin', tmp_path / 'calls.log'
    bindir.mkdir()
    docker = bindir / 'docker'
    docker.write_text('''#!/usr/bin/env bash
echo "docker $*" >> "$STUB_LOG"
if [[ "$*" == *"ps --status running --services"* ]]; then printf '%s\\n' $STUB_RUNNING; exit 0; fi
if [[ "$*" == *"check_migrations_additive"* && "${STUB_BREAKING:-0}" == "1" ]]; then exit 1; fi
exit 0
''')
    curl = bindir / 'curl'
    curl.write_text('#!/usr/bin/env bash\necho "curl $*" >> "$STUB_LOG"\nexit 0\n')
    flock = bindir / 'flock'
    flock.write_text('#!/usr/bin/env bash\nexit "${STUB_LOCK_BUSY:-0}"\n')
    for f in (docker, curl, flock):
        f.chmod(0o755)

    def run(**extra):
        env = {**os.environ, 'PATH': f'{bindir}:{os.environ["PATH"]}', 'STUB_LOG': str(log),
               'STUB_RUNNING': ' '.join(RUNNING), **extra}
        result = subprocess.run(['bash', str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True)
        lines = log.read_text().splitlines() if log.exists() else []
        return result, [line.split(' ', 1)[1] for line in lines if line.startswith('docker ')]
    return run


def verbs(calls):
    return [next(w for w in c.split() if w in ('build', 'run', 'up', 'stop', 'ps')) for c in calls]


def test_deploy_succeeds_with_workers_running_and_never_stops_them_as_a_group(stub):
    result, calls = stub()
    assert result.returncode == 0, result.stderr
    stops = [c for c in calls if ' stop ' in c]
    assert len(stops) == len(RUNNING)                      # one service per stop...
    assert all(len(c.split(' stop ')[1].split()) == 3 for c in stops)   # '-t', N, service
    assert all(c.split()[-1] in RUNNING for c in stops)


def test_order_build_then_check_then_migrate_then_roll_with_schedulers_last(stub):
    _, calls = stub()
    text = '\n'.join(calls)
    assert text.index(' build api web') < text.index('check_migrations_additive') < text.index('alembic upgrade head')
    assert text.index('alembic upgrade head') < text.index('up -d api web research-worker')
    rolled = [c.split()[-1] for c in calls if ' stop ' in c]
    assert rolled == ['worker-evidence-fetch', 'pipeline-fetch', 'pipeline-parse', 'pipeline-scheduler', 'evidence-scheduler']
    # each service is restarted right after it stops, before the next one stops
    sequence = [c.split()[-1] for c in calls if ' stop ' in c or ' up -d --no-deps ' in c]
    assert sequence == [s for svc in rolled for s in (svc, svc)]


def test_breaking_migration_aborts_before_any_migration_or_restart(stub):
    result, calls = stub(STUB_BREAKING='1')
    assert result.returncode != 0
    joined = '\n'.join(calls)
    assert 'alembic upgrade head' not in joined and ' stop ' not in joined and 'up -d api' not in joined


def test_skipping_the_worker_roll_touches_no_workers(stub):
    result, calls = stub(DEPLOY_RESTART_WORKERS='0')
    assert result.returncode == 0 and not [c for c in calls if ' stop ' in c or '--no-deps' in c]
    assert 'OLD image' in result.stdout


def test_deploy_with_no_ingestion_running_is_a_plain_deploy(stub):
    result, calls = stub(STUB_RUNNING='')
    assert result.returncode == 0 and not [c for c in calls if ' stop ' in c]
    assert any('alembic upgrade head' in c for c in calls)


def test_busy_deployment_lock_aborts_before_docker_commands(stub):
    result, calls = stub(STUB_LOCK_BUSY='1')
    assert result.returncode != 0
    assert 'Another Oracle deployment is running.' in result.stderr
    assert calls == []
