import { cleanup,fireEvent,render,screen,waitFor } from "@testing-library/react";
import { afterEach,beforeEach,describe,expect,it,vi } from "vitest";
import AssistantPage from "./page";

const getPortfolios=vi.fn();
const sendAssistantMessage=vi.fn();
vi.mock("@/lib/api",()=>({getPortfolios:(...args:unknown[])=>getPortfolios(...args),sendAssistantMessage:(...args:unknown[])=>sendAssistantMessage(...args)}));

function result(answer:string){
  return {conversation_id:"c1",message_id:"m1",answer,uncertainty:[],calculated_evidence:[],source_citations:[],freshness_warnings:[],tool_trace:[],created_at:new Date().toISOString()};
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
});
