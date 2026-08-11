import { render,screen } from "@testing-library/react";
import { describe,expect,it } from "vitest";
import { ComparisonTable,ComplianceTable } from "./DecisionTables";

describe("decision tables",()=>{
  it("renders threshold, observed value and breach magnitude",()=>{
    render(<ComplianceTable violations={[{code:"max_instrument_weight",symbol:"MEBL",actual:.194,limit:.15,breach:.044}]}/>);
    expect(screen.getByText("Maximum Instrument Weight")).toBeInTheDocument();
    expect(screen.getByText("MEBL")).toBeInTheDocument();
    expect(screen.getByText("0.0440")).toBeInTheDocument();
  });

  it("labels comparison direction without claiming execution",()=>{
    render(<ComparisonTable metrics={[{key:"volatility",label:"Volatility",unit:"decimal",current:.2,proposed:.17,delta:-.03,preferred_direction:"lower"}]}/>);
    expect(screen.getByText("Improved")).toBeInTheDocument();
    expect(screen.getByText("17.00%")).toBeInTheDocument();
  });
});
