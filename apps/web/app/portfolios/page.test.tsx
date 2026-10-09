import {cleanup,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import Page from "./page";
const mocks=vi.hoisted(()=>({replace:vi.fn(),get:vi.fn()}));
const router={replace:mocks.replace};
vi.mock("next/navigation",()=>({useRouter:()=>router}));
vi.mock("@/lib/api",()=>({getPortfolios:mocks.get}));
beforeEach(()=>vi.clearAllMocks());afterEach(cleanup);
it("opens the actual global default rather than the first portfolio",async()=>{
 mocks.get.mockResolvedValue([{id:"first",name:"Other",is_default:false},{id:"selected",name:"Selected",is_default:true}]);
 render(<Page/>);await waitFor(()=>expect(mocks.replace).toHaveBeenCalledWith("/portfolios/selected/overview"));
});
it("does not silently select a portfolio when no default exists",async()=>{
 mocks.get.mockResolvedValue([{id:"first",name:"Other",is_default:false}]);render(<Page/>);
 await screen.findByText("No global portfolio is selected.");expect(mocks.replace).not.toHaveBeenCalled();
});
