"""Encrypted, ordered replay; subscriptions only observe server-owned work."""
import asyncio
import json
import time
from datetime import timedelta
from sqlalchemy import delete, select
from app.core.security import encrypt_secret, decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution, now
from app.models.assistant_workspace import ExecutionEvent

ACTIVE = {"queued", "running"}
_batches = {}


def append(identifier, kind, payload):
    with SessionLocal.begin() as db:
        row = db.get(AssistantExecution, identifier, with_for_update=True)
        if row is None:
            return
        if kind == "terminal" and db.scalar(select(ExecutionEvent.id).where(ExecutionEvent.execution_id == identifier, ExecutionEvent.kind == "terminal")):
            return
        if kind == "text_delta":
            accounting = json.loads(row.accounting_json)
            if "first_visible_answer_ms" not in accounting:
                accounting["first_visible_answer_ms"] = round((now() - row.created_at.replace(tzinfo=now().tzinfo)).total_seconds() * 1000)
                row.accounting_json = json.dumps(accounting)
        row.event_sequence += 1
        db.add(ExecutionEvent(execution_id=identifier, sequence=row.event_sequence, kind=kind,
                              payload_encrypted=encrypt_secret(json.dumps(payload, default=str))))


def replay(db, identifier, after=0):
    return [{"sequence": row.sequence, "kind": row.kind, "payload": json.loads(decrypt_secret(row.payload_encrypted))}
            for row in db.scalars(select(ExecutionEvent).where(ExecutionEvent.execution_id == identifier,
                                     ExecutionEvent.sequence > after).order_by(ExecutionEvent.sequence).limit(200))]


def prune(db):
    expired = select(AssistantExecution.id).where(AssistantExecution.completed_at < now() - timedelta(hours=24))
    db.execute(delete(ExecutionEvent).where(ExecutionEvent.execution_id.in_(expired)))


async def subscribe(identifier, after=0):
    # Authorization is checked before opening this generator. Use short-lived sessions,
    # never hold a request DB session/transaction for the lifetime of an SSE response.
    while True:
        with SessionLocal() as db:
            row = db.get(AssistantExecution, identifier)
            events = replay(db, identifier, after)
            terminal = row.status not in ACTIVE
            snapshot = {"status": row.status, "response": json.loads(row.response_json) if row.response_json else None,
                        "error_code": row.error_code}
        for event in events:
            after = event["sequence"]
            yield f'id: {after}\ndata: {json.dumps(event, separators=(",", ":"))}\n\n'
        if terminal and len(events) < 200:
            # Also works after replay retention expires: final canonical response survives.
            yield f'event: snapshot\ndata: {json.dumps(snapshot, separators=(",", ":"))}\n\n'
            return
        yield ': keepalive\n\n'
        await asyncio.sleep(0.25)


class StreamBatch:
    def __init__(self, identifier):
        self.identifier = identifier
        _batches[identifier] = self
        self.text = []
        self.last = time.monotonic()
        self.timer = None

    def flush(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None
        if self.text:
            append(self.identifier, "text_delta", {"text": "".join(self.text)})
            self.text.clear()
        self.last = time.monotonic()

    def close(self):
        self.flush()
        if _batches.get(self.identifier) is self:
            _batches.pop(self.identifier, None)

    async def __call__(self, event):
        if event.kind == "text_delta":
            self.text.append(event.text or "")
            if time.monotonic() - self.last >= 0.25:
                self.flush()
            elif self.timer is None:
                self.timer = asyncio.get_running_loop().call_later(0.25 - (time.monotonic() - self.last), self.flush)
        elif event.kind == "tool_call":
            self.flush()
            append(self.identifier, "activity", {"text": "Reading relevant evidence", "tool": event.tool.name})
        elif event.kind == "waiting":
            self.flush()
            append(self.identifier, "activity", {"text": "Waiting for model"})
        elif event.kind == "started":
            append(self.identifier, "activity", {"text": "Generating answer"})


def save_terminal_partial(db, row):
    """Keep stopped/interrupted/error output after ephemeral replay has expired."""
    from uuid import NAMESPACE_URL, uuid5
    from app.models.workstation import AssistantMessage
    identifier = str(uuid5(NAMESPACE_URL, f"assistant-execution:{row.id}"))
    existing = db.get(AssistantMessage, identifier)
    if existing:
        existing.outcome = row.status
        return
    chunks = db.scalars(select(ExecutionEvent).where(ExecutionEvent.execution_id == row.id,
                        ExecutionEvent.kind == "text_delta").order_by(ExecutionEvent.sequence))
    text = "".join(json.loads(decrypt_secret(event.payload_encrypted)).get("text", "") for event in chunks)
    context = db.scalar(select(AssistantMessage.context_json).where(AssistantMessage.execution_id == row.id,
                        AssistantMessage.role == "user")) or "{}"
    db.add(AssistantMessage(id=identifier, conversation_id=row.conversation_id, execution_id=row.id,
        role="assistant", content=text or "No answer was completed.", context_json=context,
        outcome=row.status, evidence_json=json.dumps({"sources": [], "provisional": True, "error_code": row.error_code})))
