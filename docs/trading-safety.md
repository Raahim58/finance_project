# Trading Safety

The app must not store broker usernames or passwords.

The app must not automate broker websites or apps through Selenium, Playwright, browser control, or screen automation.

Later phases may create safe order intents:

- Draft order preview
- Simulated portfolio impact
- Explicit user confirmation
- WhatsApp or broker message draft for manual review
- Future official broker API abstraction if an authorized API is supplied

The app must not place live trades in Phase 0 or Phase 1.
