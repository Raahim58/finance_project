"""Replay captured Assistant attempts locally without printing private payloads."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.ai.providers.mock import MockProvider
from app.core.security import decrypt_secret
from app.db.session import SessionLocal
from app.models.assistant_execution import AssistantAttempt, AssistantExecution


async def replay(execution_id: str) -> dict[str, object]:
    provider = MockProvider()
    replayed = []
    with SessionLocal() as db:
        execution = db.get(AssistantExecution, execution_id)
        if execution is None:
            raise SystemExit("Execution was not found")
        attempts = list(db.scalars(
            select(AssistantAttempt)
            .where(AssistantAttempt.execution_id == execution_id)
            .order_by(AssistantAttempt.created_at)
        ))
        for attempt in attempts:
            if not attempt.payload_encrypted:
                replayed.append({
                    "attempt_id": attempt.id,
                    "operation": attempt.operation,
                    "status": "payload_unavailable",
                })
                continue
            payload = json.loads(decrypt_secret(attempt.payload_encrypted))
            messages = payload.get("messages")
            if not isinstance(messages, list):
                replayed.append({
                    "attempt_id": attempt.id,
                    "operation": attempt.operation,
                    "status": "invalid_capture",
                })
                continue
            result = await provider.chat("mock-replay-key", messages, "mock-replay")
            replayed.append({
                "attempt_id": attempt.id,
                "operation": attempt.operation,
                "status": "replayed",
                "message_count": len(messages),
                "output_bytes": len(result.content.encode("utf-8")),
            })
    return {"execution_id": execution_id, "provider": "mock", "attempts": replayed}


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id")
    args = parser.parse_args()
    # Output is structural only. Decrypted messages and mock response bodies stay in memory.
    print(json.dumps(asyncio.run(replay(args.execution_id)), indent=2))


if __name__ == "__main__":
    main()
