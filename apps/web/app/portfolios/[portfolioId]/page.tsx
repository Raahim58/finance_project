import { redirect } from "next/navigation";

export default async function PortfolioIndex({
  params,
}: {
  params: Promise<{ portfolioId: string }>;
}) {
  const { portfolioId } = await params;
  redirect(`/portfolios/${portfolioId}/overview`);
}
