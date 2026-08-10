# Security

- Passwords are hashed before storage and JWT access tokens protect user routes.
- LLM API keys are encrypted at rest, never returned after save, decrypted only server-side immediately before a provider call, and never logged in full.
- Shared ownership checks scope every portfolio, holding, transaction, allocation, IPS, analysis, scenario, monitoring, assistant, and private-document operation.
- Assistant tools are allowlisted/read-only and expose no arbitrary SQL, filesystem, network, secrets, or trade execution.
- Permanent portfolio deletion requires explicit confirmation; transaction deletion creates a reversal instead of erasing financial history.

Current deployment limitations: token revocation and application-level rate limiting are not implemented, and the local frontend stores its access token in `localStorage`. Before public deployment, use secure cookie sessions or a managed identity provider, rate limiting, secret rotation, HTTPS, database backups, restricted artifact storage, and sensitive-workflow audit logging.
