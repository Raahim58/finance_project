# Assistant provider switch

Open the Assistant and choose **Switch AI provider**. Select an active saved provider/model. This updates the account's default provider through the existing preferences API; no key entry or model call is needed. Only provider/model labels are displayed. The full encrypted API key is never returned to the browser.

The next message explicitly snapshots its provider into the run request. Already submitted runs keep their provider. Sending is disabled while the preference update is pending; a failed update preserves the previous selection. The newest active saved key determines each provider's model. Configure keys and model IDs in Settings.

No schema migration, new dependency, seed change or token-limit change is required.

From `apps/web`, use `npm ci` to install dependencies, `npm run test -- --run components/AssistantWorkspace.test.tsx` for workspace tests, `npm run typecheck` for type checks, and `npm run build` for the production build.
