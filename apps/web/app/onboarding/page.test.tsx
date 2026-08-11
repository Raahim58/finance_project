import { fireEvent,render,screen } from "@testing-library/react";
import { beforeEach,describe,expect,it,vi } from "vitest";
import OnboardingPage from "./page";

const push=vi.fn();
const saveFinancialProfile=vi.fn().mockResolvedValue({});
const updatePreferences=vi.fn().mockResolvedValue({});
vi.mock("next/navigation",()=>({useRouter:()=>({push})}));
vi.mock("@/lib/api",()=>({saveFinancialProfile:(...args:unknown[])=>saveFinancialProfile(...args),updatePreferences:(...args:unknown[])=>updatePreferences(...args)}));

describe("investor profile onboarding",()=>{
  beforeEach(()=>{push.mockClear();saveFinancialProfile.mockClear();updatePreferences.mockClear()});

  it("keeps financial capacity and behavioural willingness as separate steps",()=>{
    render(<OnboardingPage/>);
    fireEvent.change(screen.getByLabelText("Primary investment goal"),{target:{value:"Long-horizon capital growth"}});
    fireEvent.click(screen.getByRole("button",{name:/continue/i}));
    expect(screen.getByText("What losses can your finances absorb?")).toBeInTheDocument();
    expect(screen.getByLabelText("Liquid financial assets")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:/continue/i}));
    expect(screen.getByText("How do you react to uncertainty and loss?")).toBeInTheDocument();
    expect(screen.getByText(/short questionnaire is directional/i)).toBeInTheDocument();
  });
});
