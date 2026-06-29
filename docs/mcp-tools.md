# MCP-Style Tools

The app will use an internal MCP-style tool registry before any external MCP server is added.

Tool records should include:

- `name`
- `description`
- `input_schema`
- `output_schema`
- `permissions`
- `is_read_only`
- `requires_confirmation`
- `handler`

Phase 1 does not execute tools yet. Later phases must keep broker/order-intent tools behind explicit confirmation and must never automate broker websites with stored passwords.
