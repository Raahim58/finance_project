import { redirect } from "next/navigation";

export default async function LegacyPortfolioSettingsPage({params}:{params:Promise<{portfolioId:string}>}) {
  const {portfolioId}=await params;
  redirect(`/portfolios/${portfolioId}/ips`);
}
