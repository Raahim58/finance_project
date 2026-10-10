import {act,fireEvent,render,screen,waitFor,cleanup} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {ResearchEventCard} from "./ResearchEventCard";
import {ResearchBatchControl} from "./ResearchBatchControl";
import {useBrief} from "./AIBriefCard";
import type {AIBriefView} from "@/lib/api/research";
import {generateResearchBatch,previewResearchBatch,getResearchJob} from "@/lib/api/research";
vi.mock("@/lib/api/research",()=>({previewResearchBatch:vi.fn(),generateResearchBatch:vi.fn(),getResearchJob:vi.fn(),getEvidencePage:vi.fn()}));
const event={id:"e",event_key:"raw:e",raw_event_id:"e",normalized_event_id:"n",title:"Quarterly results announced",occurred_at:"2026-08-12T00:00:00Z",event_type:"earnings",source_document_type:"announcement",materiality:"high",freshness_status:"recent",factors:[],subjects:[{subject_key:"AAA"}],evidence:[],relationship_kind:"ai_proposed_indirect"};
const preview={companies:[{instrument_id:"a",symbol:"AAA",reports_to_index:2,profile_cached:false,digest_cached:false,selected_events:1,max_calls:2}],maximum_calls:2,budget_calls:16,within_budget:true,provider_config:{provider:"gemini",model:"configured-model"},estimated_input_tokens_upper_bound:18000,estimated_output_tokens_upper_bound:4000};
const job={id:"j",status:"queued",error_code:null,reserved_calls:0,maximum_calls:16,actual_usage:{input_tokens:0,output_tokens:0,reasoning_tokens:0},usage_complete:true,companies:[{id:"c",instrument_id:"a",status:"queued",error_code:null,result:{symbol:"AAA"}}]};
afterEach(()=>{cleanup();vi.useRealTimers()});beforeEach(()=>vi.clearAllMocks());
describe("research intelligence",()=>{
 it("shows proposed indirect matches and missing saved explanations",()=>{render(<ResearchEventCard event={event} weight={null}/>);expect(screen.getByText("AI-proposed indirect")).toBeInTheDocument();expect(screen.getByText("Portfolio weight unavailable")).toBeInTheDocument();expect(screen.getByText("Saved explanation not generated.")).toBeInTheDocument();expect(screen.getByRole("link",{name:"AAA"})).toHaveAttribute("href","/companies/AAA")});
 it("generates only after preview using the reviewed request",async()=>{vi.mocked(previewResearchBatch).mockResolvedValue(preview);vi.mocked(generateResearchBatch).mockResolvedValue(job);render(<ResearchBatchControl instrumentIds={["a"]} onComplete={()=>{}}/>);expect(previewResearchBatch).not.toHaveBeenCalled();expect(generateResearchBatch).not.toHaveBeenCalled();fireEvent.click(screen.getByRole("button",{name:"Preview generation"}));await screen.findByRole("button",{name:"Generate saved explanations"});expect(generateResearchBatch).not.toHaveBeenCalled();fireEvent.click(screen.getByRole("button",{name:"Generate saved explanations"}));await waitFor(()=>expect(generateResearchBatch).toHaveBeenCalledWith(vi.mocked(previewResearchBatch).mock.calls[0][0]));expect(vi.mocked(generateResearchBatch).mock.calls[0][0]).toMatchObject({instrument_ids:["a"],max_calls:16,max_companies:8});await screen.findByText(/Queued for research worker/)});
 it("clears reviewed generation when portfolio scope changes",async()=>{vi.mocked(previewResearchBatch).mockResolvedValue(preview);const {rerender}=render(<ResearchBatchControl portfolioId="p1" onComplete={()=>{}}/>);fireEvent.click(screen.getByRole("button",{name:"Preview generation"}));await screen.findByRole("button",{name:"Generate saved explanations"});rerender(<ResearchBatchControl portfolioId="p2" onComplete={()=>{}}/>);expect(screen.queryByRole("button",{name:"Generate saved explanations"})).not.toBeInTheDocument();expect(generateResearchBatch).not.toHaveBeenCalled()});
 it("polls completion and refreshes reads once",async()=>{vi.mocked(previewResearchBatch).mockResolvedValue(preview);vi.mocked(generateResearchBatch).mockResolvedValue(job);vi.mocked(getResearchJob).mockResolvedValue({...job,status:"completed",reserved_calls:2,actual_usage:{input_tokens:200,output_tokens:100,reasoning_tokens:0},companies:[{...job.companies[0],status:"completed"}]});const done=vi.fn();render(<ResearchBatchControl instrumentIds={["a"]} onComplete={done}/>);fireEvent.click(screen.getByRole("button",{name:"Preview generation"}));await screen.findByRole("button",{name:"Generate saved explanations"});fireEvent.click(screen.getByRole("button",{name:"Generate saved explanations"}));await screen.findByText(/Queued for research worker/);await waitFor(()=>expect(done).toHaveBeenCalledTimes(1),{timeout:3500});expect(screen.getByText(/Reported tokens: 200 input \/ 100 output/)).toBeInTheDocument();expect(getResearchJob).toHaveBeenCalledTimes(1)});
});

const pendingBrief = {status:"generating",current:false,brief:null,facts:[],generated_at:null,provider:null,model:null} satisfies AIBriefView;
const readyBrief = (headline:string):AIBriefView => ({...pendingBrief,status:"ready",current:true,brief:{headline,summary:"Fixture",sections:[],events:[]}});
function BriefProbe({load}:{load:(retry:boolean)=>Promise<AIBriefView>}) {
 const state=useBrief(load);
 return <><span data-testid="brief-state">{state.view?.status??"loading"}</span><span>{state.view?.brief?.headline}</span><button onClick={state.retry}>Retry brief</button></>;
}
describe("brief cache polling",()=>{
 afterEach(()=>vi.useRealTimers());
 it("keeps polling beyond the old short window and reaches the completed cache",async()=>{
  vi.useFakeTimers();let calls=0;
  const load=vi.fn(async()=>++calls<20?pendingBrief:readyBrief("Complete"));
  render(<BriefProbe load={load}/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(100_000)});
  expect(screen.getByText("Complete")).toBeInTheDocument();
  expect(load).toHaveBeenCalledTimes(20);
 });
 it("recovers a transient read and polls again after manual retry",async()=>{
  vi.useFakeTimers();
  const load=vi.fn().mockRejectedValueOnce(new Error("temporary timeout")).mockResolvedValueOnce(readyBrief("Saved"))
   .mockResolvedValueOnce(pendingBrief).mockResolvedValue(readyBrief("Refreshed"));
  render(<BriefProbe load={load}/>);
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});
  expect(screen.getByText("Saved")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Retry brief"}));
  await act(async()=>{await vi.advanceTimersByTimeAsync(5000)});
  expect(screen.getByText("Refreshed")).toBeInTheDocument();
  expect(load.mock.calls.map(args=>args[0])).toEqual([false,false,true,false]);
 });
 it("ignores late results from a previous scope",async()=>{
  let finish!:(value:AIBriefView)=>void;
  const old=vi.fn(()=>new Promise<AIBriefView>(resolve=>{finish=resolve}));
  const next=vi.fn(async()=>readyBrief("New scope"));
  const view=render(<BriefProbe load={old}/>);
  view.rerender(<BriefProbe load={next}/>);
  await screen.findByText("New scope");
  await act(async()=>{finish(readyBrief("Old scope"))});
  expect(screen.queryByText("Old scope")).not.toBeInTheDocument();
 });
});
