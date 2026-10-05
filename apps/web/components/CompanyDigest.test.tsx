import {act,cleanup,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {CompanyDigestPanel} from "./CompanyDigest";
import {getCompanyDigest} from "@/lib/api/research";
vi.mock("@/lib/api/research",()=>({getCompanyDigest:vi.fn(),retryCompanyDigest:vi.fn()}));
const ready={status:"ready",current:true,brief_is_current:true,input_hash:"current",brief_input_hash:"current",job_id:null,error_code:null,generated_at:"2026-10-05T00:00:00Z",brief_sources:{S1:[{title:"Audited report",source_url:"https://example.test/report"}]},snapshot:null,brief:{thesis:[{text:"Expansion is conditional.",kind:"interpretation" as const,refs:["S1"]}],earnings_drivers:[],valuation:[],catalysts:[],risks:[],unresolved_questions:[]}};
beforeEach(()=>vi.clearAllMocks());afterEach(()=>{cleanup();vi.useRealTimers()});
it("renders the saved cited brief without generating from the browser",async()=>{
 vi.mocked(getCompanyDigest).mockResolvedValue(ready);
 render(<CompanyDigestPanel symbol="LUCK"/>);
 await screen.findByText("Expansion is conditional.");
 expect(screen.getByRole("link",{name:"Audited report"})).toHaveAttribute("href","https://example.test/report");
 expect(getCompanyDigest).toHaveBeenCalledTimes(1);
 expect(getCompanyDigest).toHaveBeenCalledWith("LUCK",true);
});
it("ignores a previous company's delayed response after navigation",async()=>{
 let resolve!:(value:typeof ready)=>void;
 vi.mocked(getCompanyDigest).mockImplementation(symbol=>symbol==="LUCK"?new Promise(r=>{resolve=r}):Promise.resolve({...ready,brief:{...ready.brief,thesis:[{...ready.brief.thesis[0],text:"FFC brief."}]}}));
 const view=render(<CompanyDigestPanel symbol="LUCK"/>);
 view.rerender(<CompanyDigestPanel symbol="FFC"/>);
 await screen.findByText("FFC brief.");
 await act(async()=>resolve(ready));
 expect(screen.queryByText("Expansion is conditional.")).not.toBeInTheDocument();
});
it("keeps the previous brief and its sources visible when refresh fails",async()=>{
 vi.mocked(getCompanyDigest).mockResolvedValue({...ready,status:"failed",current:false,brief_is_current:false,brief_input_hash:"older"});
 render(<CompanyDigestPanel symbol="LUCK"/>);
 await screen.findByText("Expansion is conditional.");
 expect(screen.getByRole("button",{name:"Retry brief"})).toBeInTheDocument();
 expect(screen.getByRole("link",{name:"Audited report"})).toBeInTheDocument();
});
it("stops polling after unmount",async()=>{
 vi.useFakeTimers();vi.mocked(getCompanyDigest).mockResolvedValue({...ready,status:"queued",current:false,brief:null});
 const view=render(<CompanyDigestPanel symbol="LUCK"/>);
 await act(async()=>{});view.unmount();
 await act(async()=>vi.advanceTimersByTime(6000));
 expect(getCompanyDigest).toHaveBeenCalledTimes(1);
});
