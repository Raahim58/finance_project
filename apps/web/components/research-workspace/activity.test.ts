import {describe,it,expect} from "vitest";
import {activityRows,activityWithin} from "./activity";
import {money} from "./formatting";
import type {AuditEvent,Transaction} from "@/lib/api";
describe("stored activity presentation",()=>{
 it("merges dated audit events and ledger records newest first without discarding same identifiers",()=>{const transaction={id:"same",portfolio_id:"owned",transaction_date:"2026-07-13",transaction_type:"buy",symbol:"MARI"} as Transaction;const event={id:"same",portfolio_id:"owned",created_at:"2026-10-02T10:00:00Z",entity_type:"proposal",event_type:"allocation_created"} as AuditEvent;const rows=activityRows([transaction],[event]);expect(rows.map(row=>row.id)).toEqual(["audit:same","transaction:same"]);expect(rows[1].transaction).toBe(transaction)});
 it("distinguishes absent price from stored zero",()=>{expect(money(null)).toBe("—");expect(money(undefined)).toBe("—");expect(money("0")).toBe("PKR 0")});
 it("applies relative date filters using the stored time rather than an invented session date",()=>{const now=Date.parse("2026-10-08T12:00:00Z");expect(activityWithin("2026-10-07","7",now)).toBe(true);expect(activityWithin("2026-07-13","7",now)).toBe(false);expect(activityWithin("2026-07-13","",now)).toBe(true)});
});
