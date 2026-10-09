import { Suspense } from "react";

import { SettingsWorkspace } from "@/components/settings/SettingsWorkspace";

export default function SettingsPage() {
  return <Suspense fallback={null}><SettingsWorkspace /></Suspense>;
}
