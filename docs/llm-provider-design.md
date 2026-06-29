# LLM Provider Design

The backend exposes an `LLMProvider` interface with:

- `name`
- `validate_key()`
- `chat()`
- `stream_chat()`
- `supports_tool_calling`
- `supports_json_mode`
- `max_context_tokens`
- `default_model`

Implemented in Phase 1:

- `MockProvider`
- Anthropic, OpenAI, Gemini, and OpenRouter adapter placeholders
- Provider registry
- Encrypted key storage model and API

User keys are encrypted at rest and only masked values are returned to the frontend.
