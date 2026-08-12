import {describe,expect,it} from "vitest";
import {formatMetric,normalizeWeights,weightSummary} from "./analytics";

describe("analytical presentation contract",()=>{
  it("formats every supported unit from the unit field",()=>{
    expect({
      decimal:formatMetric(.125,"decimal"),
      percentagePoint:formatMetric(-.75,"percentage_point"),
      ratio:formatMetric(.25,"ratio"),
      currency:formatMetric(1234.5,"PKR"),
      days:formatMetric(12,"days"),
      count:formatMetric(4,"count"),
    }).toEqual({decimal:"12.50%",percentagePoint:"-0.75 pp",ratio:"0.25",currency:"PKR 1,234.5",days:"12 days",count:"4"});
  });

  it("uses the API tolerance and normalizes displayed edited weights exactly",()=>{
    const edited={MEBL:.3333,SYS:.3333,CASH:.3333};
    expect(weightSummary(edited)).toMatchObject({valid:false});
    const normalized=normalizeWeights(edited);
    expect(weightSummary(normalized)).toMatchObject({valid:true});
    expect(Object.values(normalized).reduce((sum,value)=>sum+value,0)).toBeCloseTo(1,12);
  });
});
