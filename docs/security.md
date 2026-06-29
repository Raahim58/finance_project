# Security

Phase 1 security controls:

- Passwords are hashed before storage.
- JWT access tokens protect user-specific routes.
- LLM API keys are encrypted at rest with `ENCRYPTION_KEY`.
- Full LLM API keys are never returned to the frontend.
- Full LLM API keys must never be logged.
- `.env` files are ignored by git.

Known MVP limitations:

- Token revocation is not implemented yet.
- Rate limiting is not implemented yet.
- Frontend stores the access token in `localStorage` for local MVP simplicity.

Before production, use secure cookie sessions or an auth provider, add rate limiting, rotate secrets, and add audit logging for sensitive workflows.
