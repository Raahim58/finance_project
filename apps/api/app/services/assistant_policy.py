"""Versioned chat ceilings, isolated from the unchanged background-generation policy."""
import json
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantExecution
from app.services.assistant_diagnostics import execution_id


def selected_policy():
    second = settings.assistant_token_trial == "trial2"
    return {"version": "phase11-" + settings.assistant_token_trial + "-v1", "input": 96000 if second else 48000,
            "output": 8192, "calls": 6, "cumulative_input": 180000, "cumulative_output": 24000,
            "history": 64000 if second else 24000, "recent": 32000 if second else 12000,
            "summary": 4000 if second else 3000, "thinking": True}


def execution_policy():
    identifier = execution_id.get()
    if identifier:
        with SessionLocal() as db:
            row = db.get(AssistantExecution, identifier)
            if row and row.policy_json != "{}":
                return json.loads(row.policy_json)
    return selected_policy()
