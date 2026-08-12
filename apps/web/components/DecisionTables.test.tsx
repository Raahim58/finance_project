import { render,screen } from "@testing-library/react";
import { describe,expect,it } from "vitest";
import { ComparisonTable,ComplianceTable } from "./DecisionTables";

describe("decision tables",()=>{
  it("renders threshold, observed value and breach magnitude",()=>{
    render(<ComplianceTable status="BREACH" checks={[]} not_evaluated={[]} violations={[{code:"max_instrument_weight",symbol:"MEBL",actual:.194,limit:.15,breach:.044}]}/>);
    expect(screen.getByText("Maximum Instrument Weight")).toBeInTheDocument();
    expect(screen.getByText("MEBL")).toBeInTheDocument();
    expect(screen.getByText("BREACH")).toBeInTheDocument();
  });

  it("labels comparison direction without claiming execution",()=>{
    render(<ComparisonTable metrics={[{key:"volatility",label:"Volatility",unit:"decimal",current:.2,proposed:.17,delta:-.03,preferred_direction:"lower"}]}/>);
    expect(screen.getByText("Improved")).toBeInTheDocument();
    expect(screen.getByText("17.00%")).toBeInTheDocument();
  });

  it("never turns empty violations plus unavailable checks into a pass",()=>{
    const unavailable=["valuation","sector","beta","liquidity"].map(code=>({code,label:code,message:`${code} input missing`,status:"NOT_EVALUATED"}));
    render(<ComplianceTable status="NOT_EVALUATED" checks={unavailable} violations={[]} not_evaluated={unavailable}/>);
    expect(screen.getByText("Not fully evaluated")).toBeInTheDocument();
    expect(screen.getAllByText(/input missing/)).toHaveLength(4);
    expect(screen.queryByText("Within evaluated mandate")).not.toBeInTheDocument();
  });

  it("labels exact zero changes unchanged and formats ratios without percent scaling",()=>{
    render(<ComparisonTable metrics={[{key:"sharpe",label:"Sharpe ratio",unit:"ratio",current:-.773,proposed:-.773,delta:0,preferred_direction:"higher"},{key:"beta",label:"Portfolio beta",unit:"ratio",current:.25,proposed:.25,delta:0,preferred_direction:"neutral"}]}/>);
    expect(screen.getByText("Unchanged")).toBeInTheDocument();
    expect(screen.getAllByText("-0.77")).toHaveLength(2);
    expect(screen.getAllByText("0.25")).toHaveLength(2);
    expect(screen.queryByText("-77.30%")).not.toBeInTheDocument();
    expect(screen.queryByText("Worsened")).not.toBeInTheDocument();
  });
});
