# LLM Provider and Assistant Design

The provider registry supports a deterministic mock provider and encrypted key records for OpenAI, Anthropic, Gemini, and OpenRouter. External HTTP provider calls remain deployment adapters; when unavailable, the orchestrator returns its deterministic evidence synthesis rather than fabricating an LLM answer.

The assistant itself is implemented independently of provider choice. It authorizes scope, invokes only typed internal tools, collects database provenance and document citations, enforces iteration/chunk/time limits, validates numerical grounding, and persists the tool/run trace. Full keys remain encrypted at rest, are never returned to the frontend, and are only decrypted server-side immediately before a configured provider call.
