import { cleanup,render,screen } from "@testing-library/react";
import { afterEach,describe,expect,it } from "vitest";
import { TermHelp } from "./TermHelp";

describe("TermHelp",()=>{
  afterEach(()=>cleanup());

  it("exposes complex-term help to pointer and keyboard users",()=>{
    render(<TermHelp term="Risk contribution"/>);
    const trigger=screen.getByRole("button",{name:"Explain Risk contribution"});
    const tooltip=screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("aria-describedby",tooltip.id);
    expect(tooltip).toHaveTextContent("modeled share of total risky-asset variance");
  });
});
