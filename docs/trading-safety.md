# Trading Safety

The workstation does not store broker usernames/passwords, automate broker websites/apps, or place orders. Selenium, Playwright browser control, screen automation, and password scraping are forbidden for broker access.

Optimizer allocations and rebalance previews are immutable/read-only proposals. They may be reviewed or exported manually, but never change holdings or create a live order. Recommendation acceptance only records the user decision; it does not execute the recommendation.

A future official broker API could support a separately permissioned order-intent workflow, but every write-like operation would require explicit user confirmation. Broker-password automation and autonomous trade execution remain permanently out of scope.
