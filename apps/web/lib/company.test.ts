import { expect, it } from "vitest";
import { companyFacts, factValue, ratioValue } from "./company";
import type { CompanyResearch } from "./api";

it("preserves the structured statement period, basis and exact value",()=>{
  const research={context:{sections:{company_facts:{data:{fundamentals:[{id:"f1",metric:"cash",value:"0",unit:"PKR",currency:"PKR",period_end:"2026-06-30",accounting_basis:"consolidated",source:"Cash and equivalents"}]}}}},fundamentals:[]} as unknown as CompanyResearch;
  expect(companyFacts(research)[0]).toMatchObject({id:"f1",value:"0",period_end:"2026-06-30",accounting_basis:"consolidated"});
  expect(factValue(companyFacts(research)[0].value,"PKR","PKR")).toBe("PKR 0");
});
it("keeps missing values missing and respects percent versus multiple units",()=>{
  expect(factValue(null,"percent")).toBe("—");
  expect(factValue("18.2","percent")).toBe("18.2%");
  expect(factValue("0.182","fraction")).toBe("18.2%");
  expect(factValue("1.25","ratio")).toBe("1.25×");
});
it("does not turn incomplete facts or screening estimates into a ratio",()=>{
  const research={derived_fundamentals:{ratios:{}},market_research:{screening_metrics:{net_margin:"0.7"}}} as unknown as CompanyResearch;
  expect(ratioValue(research,"cash_ratio")).toBeUndefined();
  expect(ratioValue(research,"net_margin")).toBeUndefined();
});
