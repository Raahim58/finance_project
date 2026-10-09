"use client";
import { useParams } from "next/navigation";
import { CompanyWorkspace } from "@/components/company/CompanyWorkspace";
export default function CompanyPage() {
  const { symbol } = useParams<{symbol:string}>();
  return <CompanyWorkspace key={symbol.toUpperCase()} symbol={symbol.toUpperCase()} />;
}
