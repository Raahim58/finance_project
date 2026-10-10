from celery import Celery

from app.core.config import settings

celery_app = Celery("psx_phase2", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.update(
    imports=("app.jobs.macro_tasks", "app.jobs.pipeline_tasks"),
    task_routes={
        "pipeline.execute": {"queue": "pipeline_parse"},
        "macro.refresh_series": {"queue": "macro"},
    },
    result_backend_transport_options={"visibility_timeout":1800},
    visibility_timeout=1800,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_log_color=False,
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_transport_options={
        "visibility_timeout": 1800,
        "priority_steps": list(range(10)),
        "sep": ":",
        "queue_order_strategy": "priority",
    },
)

app = celery_app
