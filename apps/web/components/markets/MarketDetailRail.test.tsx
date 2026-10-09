import {act,cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {getCompanyHistory,getDocuments,getPortfolioSummary,getPortfolios,type Company,type MarketOverview,type PortfolioSummary} from "@/lib/api";
import {MarketDetailRail} from "./MarketDetailRail";
vi.mock("@/lib/api",()=>({getCompanyHistory:vi.fn(),getDocuments:vi.fn(),getPortfolioSummary:vi.fn(),getPortfolios:vi.fn()}));
vi.mock("@/components/AssistantWorkspace",()=>({useAssistantWorkspace:()=>({open:vi.fn()})}));
vi.mock("./IndexChart",()=>({IndexChart:()=>null}));
const companies=[{symbol:"FFC",name:"Fauji Fertilizer",sector:"Fertilizer"},{symbol:"EFERT",name:"Engro Fertilizers",sector:"Fertilizer"},{symbol:"SYS",name:"Systems",sector:"Technology"}] as Company[];
const portfolio={id:"one",name:"Stored portfolio",is_default:true},summary={portfolio,total_value:"1000",valuation_complete:true,holdings:[{symbol:"FFC",sector:"Fertilizer",market_value:"250"}],data_freshness_date:"2026-10-08"} as unknown as PortfolioSummary;
const market={prices:[{symbol:"FFC",close:"500",change_percent:"1",volume:100,trade_date:"2026-10-08",source:"Stored quote"},{symbol:"EFERT",close:"200",change_percent:"-1",volume:200,trade_date:"2026-10-08",source:"Stored quote"}],top_gainers:[],top_losers:[],top_volume:[],sectors:[]} as unknown as MarketOverview;
afterEach(cleanup);
beforeEach(()=>{vi.resetAllMocks();vi.mocked(getPortfolios).mockResolvedValue([portfolio] as any);vi.mocked(getPortfolioSummary).mockResolvedValue(summary);vi.mocked(getCompanyHistory).mockResolvedValue([]);vi.mocked(getDocuments).mockResolvedValue([]);});
describe("market detail evidence",()=>{
 it("searches only the selected sector and displays stored holding weights",async()=>{
  const onCompany=vi.fn();render(<MarketDetailRail selection={{kind:"sector",sector:"Fertilizer"}} companies={companies} market={market} onClose={vi.fn()} onCompany={onCompany}/>);
  await screen.findByText("25.00%");expect(screen.queryByText("SYS")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Search companies in Fertilizer"),{target:{value:"Engro"}});
  expect(screen.getByText("EFERT")).toBeInTheDocument();expect(screen.queryByText("FFC")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:/EFERT/}));expect(onCompany).toHaveBeenCalledWith("EFERT");
 });
 it("does not publish weights from a partial valuation",async()=>{
  vi.mocked(getPortfolioSummary).mockResolvedValue({...summary,valuation_complete:false});
  render(<MarketDetailRail selection={{kind:"sector",sector:"Fertilizer"}} companies={companies} market={market} onClose={vi.fn()} onCompany={vi.fn()}/>);
  await screen.findByText(/valuation is incomplete/);expect(screen.queryByText("25.00%")).not.toBeInTheDocument();expect(screen.getByText("Unavailable")).toBeInTheDocument();
 });
 it("does not select an arbitrary portfolio or manufacture missing history",async()=>{
  vi.mocked(getPortfolios).mockResolvedValue([{...portfolio,is_default:false}] as any);
  const close=vi.fn();render(<MarketDetailRail selection={{kind:"company",symbol:"FFC"}} companies={companies} market={market} onClose={close} onCompany={vi.fn()}/>);
  await screen.findByText("Select a portfolio to see holding weights.");expect(getPortfolioSummary).not.toHaveBeenCalled();
  expect(screen.getByRole("link",{name:/Open company/})).toHaveAttribute("href","/companies/FFC");
  fireEvent.click(screen.getByRole("button",{name:"Close market detail"}));expect(close).toHaveBeenCalled();
 });
 it("ignores late previous-portfolio valuations after global selection changes",async()=>{
  let finish!:(value:PortfolioSummary)=>void;
  vi.mocked(getPortfolioSummary).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve})).mockResolvedValueOnce({...summary,portfolio:{...summary.portfolio,id:"two",name:"New selected portfolio"},total_value:"2000"});
  render(<MarketDetailRail selection={{kind:"sector",sector:"Fertilizer"}} companies={companies} market={market} onClose={vi.fn()} onCompany={vi.fn()}/>);
  await waitFor(()=>expect(getPortfolioSummary).toHaveBeenCalledWith("one"));
  vi.mocked(getPortfolios).mockResolvedValue([{...portfolio,id:"two"}] as any);act(()=>window.dispatchEvent(new Event("psx-portfolio-change")));
  await screen.findByText("12.50%");await act(async()=>finish(summary));
  expect(screen.queryByText("25.00%")).not.toBeInTheDocument();expect(screen.getByText("12.50%")).toBeInTheDocument();
 });
});
