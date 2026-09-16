import { cleanup,fireEvent,render,screen,waitFor } from "@testing-library/react";
import { afterEach,beforeEach,describe,expect,it,vi } from "vitest";
import AssistantPage from "./page";

const getPortfolios=vi.fn();
const sendAssistantMessage=vi.fn();
vi.mock("@/lib/api",()=>({activeAssistantExecution:()=>null,acknowledgeAssistantExecution:vi.fn(),resumeAssistantExecution:vi.fn(),getPortfolios:(...args:unknown[])=>getPortfolios(...args),sendAssistantMessage:(...args:unknown[])=>sendAssistantMessage(...args)}));

function result(answer:string,diagnosticIds:string[]=[]){
  return {conversation_id:"c1",message_id:"m1",answer,uncertainty:[],calculated_evidence:[],source_citations:[],freshness_warnings:[],tool_trace:[],synthesis:{mode:"llm_tool_loop",provider:"gemini",model:"gemini-3-flash-preview",diagnostic_ids:diagnosticIds,token_usage:{input_tokens:1234,output_tokens:321,total_tokens:1555,model_calls:1,reported_by_provider:true}},created_at:new Date().toISOString()};
}

describe("assistant scope and async correctness",()=>{
  beforeEach(()=>{getPortfolios.mockReset();sendAssistantMessage.mockReset()});
  afterEach(()=>cleanup());

  it("defaults to the globally selected portfolio once the portfolio list resolves",async()=>{
    let resolvePortfolios:(rows:unknown[])=>void=()=>{};
    getPortfolios.mockReturnValue(new Promise(resolve=>{resolvePortfolios=resolve}));
    render(<AssistantPage/>);
    expect(screen.getByLabelText("Portfolio scope")).toHaveValue("");
    resolvePortfolios([{id:"p1",name:"Growth",is_default:true}]);
    await waitFor(()=>expect(screen.getByRole("option",{name:"Growth"})).toBeInTheDocument());
    await waitFor(()=>expect(screen.getByLabelText("Portfolio scope")).toHaveValue("p1"));
  });

  it("does not let a slower earlier request overwrite the result of a newer one",async()=>{
    getPortfolios.mockResolvedValue([]);
    let resolveFirst:(value:unknown)=>void=()=>{};
    sendAssistantMessage.mockImplementationOnce(()=>new Promise(resolve=>{resolveFirst=resolve}));
    sendAssistantMessage.mockImplementationOnce(()=>Promise.resolve(result("second answer")));
    const {container}=render(<AssistantPage/>);
    const textbox=screen.getByLabelText("Question");
    const form=container.querySelector("form") as HTMLFormElement;
    // The submit button disables itself while a request is in flight, so this fires
    // the form's submit event directly to exercise the request-sequencing guard even
    // if a future change relaxes that disabled state.
    const submit=()=>fireEvent.submit(form);

    fireEvent.change(textbox,{target:{value:"first question"}});
    submit();
    fireEvent.change(textbox,{target:{value:"second question"}});
    submit();

    await waitFor(()=>expect(screen.getByText("second answer")).toBeInTheDocument());
    resolveFirst(result("first answer (stale)"));
    await new Promise(r=>setTimeout(r,0));
    expect(screen.queryByText("first answer (stale)")).not.toBeInTheDocument();
    expect(screen.getByText("second answer")).toBeInTheDocument();
  });

  it("shows provider-reported input and output token usage",async()=>{
    getPortfolios.mockResolvedValue([{id:"p1",name:"Growth",is_default:true}]);
    sendAssistantMessage.mockResolvedValue(result("token answer"));
    const {container}=render(<AssistantPage/>);
    fireEvent.change(screen.getByLabelText("Question"),{target:{value:"Analyze MEBL"}});
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    await waitFor(()=>expect(screen.getByText(/Input 1,234 · Output 321 · Total 1,555/)).toBeInTheDocument());
  });

  it("shows a short server-side diagnostic reference",async()=>{
    getPortfolios.mockResolvedValue([{id:"p1",name:"Growth",is_default:true}]);
    sendAssistantMessage.mockResolvedValue(result("failed answer",["12345678-abcd-efab-cdef-1234567890ab"]));
    const {container}=render(<AssistantPage/>);
    fireEvent.change(screen.getByLabelText("Question"),{target:{value:"Analyze MEBL"}});
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    await waitFor(()=>expect(screen.getByText("Diagnostic 12345678")).toBeInTheDocument());
  });

  it("renders grounded web citations as external links",async()=>{
    getPortfolios.mockResolvedValue([{id:"p1",name:"Growth",is_default:true}]);
    sendAssistantMessage.mockResolvedValue({...result("verified answer"),source_citations:[{id:"web-1",title:"Recent filing",source_name:"Gemini web grounding",source_url:"https://example.com/filing"}]});
    const {container}=render(<AssistantPage/>);
    fireEvent.change(screen.getByLabelText("Question"),{target:{value:"Verify the recent filing"}});
    fireEvent.submit(container.querySelector("form") as HTMLFormElement);

    const link=await screen.findByRole("link",{name:"Recent filing"});
    expect(link).toHaveAttribute("href","https://example.com/filing");
  });
});

it("renders server allocation rows and separate evidence outcomes",async()=>{
  getPortfolios.mockResolvedValue([]);
  const base=result("Model narrative\n- first item\n- second item");
  sendAssistantMessage.mockResolvedValue({...base,tool_trace:[{tool:"allocation.verify"}],source_citations:[{source_name:"Stored IPS"}],synthesis:{...base.synthesis,allocation_check:{status:"accepted",verification_id:"verify-1",rows:[{instrument_id:"m",symbol:"MEBL",current_capital_weight:.4,proposed_capital_weight:.5,side:"buy",quantity:"2",gross_amount:"200",currency:"PKR"},{instrument_id:"CASH",symbol:"CASH",current_capital_weight:.6,proposed_capital_weight:.5}],checks:{price_freshness:{status:"stale"},ips_compliance:{status:"PASS"},modeled_goal:{status:"below",required_return:.2,proposed_modeled_return:.1,shortfall:.1}},evidence_readiness:{status:"insufficient_evidence",actionable_recommendation_eligible:false}}}});
  const {container}=render(<AssistantPage/>);
  fireEvent.change(screen.getByLabelText("Question"),{target:{value:"Recommend weights"}});
  fireEvent.submit(container.querySelector("form") as HTMLFormElement);
  await screen.findByRole("table");
  expect(screen.getByRole("rowheader",{name:"MEBL"})).toBeInTheDocument();
  expect(screen.getByRole("rowheader",{name:"CASH"})).toBeInTheDocument();
  expect(screen.getByText("Prices: stale")).toBeInTheDocument();
  expect(screen.getByText("Below modeled goal")).toBeInTheDocument();
  expect(screen.getByText("Insufficient evidence for an actionable recommendation.")).toBeInTheDocument();
  expect(screen.getByText("Model narrative - first item - second item").textContent).toBe("Model narrative\n- first item\n- second item");
  expect(screen.getByRole("heading",{name:"Cited evidence"})).toBeInTheDocument();
  expect(screen.getByText("Stored IPS",{selector:"strong"})).toBeInTheDocument();
  cleanup();
});
