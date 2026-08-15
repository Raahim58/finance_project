from celery import Celery

from app.core.config import settings

celery_app = Celery("psx_phase2", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.update(
    imports=("app.jobs.phase2_tasks", "app.jobs.evidence_tasks"),
    task_routes={
        "phase2.broad_fundamentals": {"queue": "broad_fundamentals"},
        "phase2.dps_history": {"queue": "dps_history"},
        "phase2.financial_download_catalog": {"queue": "financial_download"},
        "phase2.financial_download_pdf": {"queue": "financial_download"},
        "phase2.financial_extract": {"queue": "financial_extract"},
        "evidence.discover": {"queue": "evidence_discovery"},
        "evidence.fetch": {"queue": "evidence_fetch"},
        "evidence.parse": {"queue": "evidence_parse"},
        "evidence.pdf": {"queue": "evidence_pdf"},
        "evidence.index": {"queue": "evidence_index"},
        "evidence.targeted_refresh": {"queue": "evidence_discovery"},
        "evidence.historical_hydrate": {"queue": "historical_hydrate"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_log_color=False,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_transport_options={
        "priority_steps": list(range(10)),
        "sep": ":",
        "queue_order_strategy": "priority",
    },
)

app = celery_app
