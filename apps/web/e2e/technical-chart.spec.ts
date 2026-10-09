import { expect, test } from "@playwright/test";
// Offline synthetic fixtures for UI verification only; never seeded as market data.
const rows=Array.from({length:2000},(_,i)=>{
  const date=new Date(Date.UTC(2020,6,i+1)),close=100+i*.05+Math.sin(i*.3)*6;
  return {symbol:"TEST",trade_date:date.toISOString().slice(0,10),open:String(close-1),high:String(close+2),low:String(close-2),close:String(close),previous_close:String(close-1),change:"1",change_percent:"1",volume:10000+(i%27===0?50000:i%7*1000),value:"1000000",source:"demo_ui_fixture",source_url:"https://example.test/history",ingested_at:"2026-05-16T00:00:00Z"};
}).reverse();
const end=rows[0].trade_date;
test.beforeEach(async({page})=>{
  await page.addInitScript(()=>localStorage.setItem("psx_ai_token","offline-chart-test-token"));
  await page.route("**/api/**",async route=>{
    const url=new URL(route.request().url()),path=url.pathname.replace(/^\/api/,"");let body:unknown=[];
    if(path==="/auth/me")body={id:"fixture-user",email:"fixture@example.test",full_name:"Chart tester"};
    else if(path==="/research/instruments"||path==="/instruments")body=[{id:"fixture",symbol:"TEST",name:"Offline chart fixture"}];
    else if(path==="/market/company/TEST")body={company:{symbol:"TEST",name:"Offline chart fixture",sector:"Test sector",exchange:{code:"PSX"}},latest_price:rows[0]};
    else if(path==="/market/company/TEST/history")body=rows.filter(row=>(!url.searchParams.get("start_date")||row.trade_date>=url.searchParams.get("start_date")!)&&(!url.searchParams.get("end_date")||row.trade_date<=url.searchParams.get("end_date")!));
    else if(path==="/market/freshness")body={is_stale:false,latest_trade_date:end,exchange_session_note:"Offline fixture session"};
    else if(path.includes("/completeness"))body={price:{available:true,observations:rows.length}};
    else if(path.endsWith("/overview"))body={instrument:{id:"fixture",symbol:"TEST"},fundamentals:[],portfolio_relevance:[],context:{sections:{}},derived_fundamentals:{ratios:{}},has_synthetic_data:false};
    else if(path.includes("/digest"))body={status:"provider_unavailable",brief:null,prepared_intelligence:[]};
    else if(path.endsWith("/intelligence"))body={symbol:"TEST",events:[],reports:[]};
    await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
  });
});
test("native ECharts renders candles, overlays and one synchronized lower pane",async({page})=>{
  const exceptions:string[]=[];page.on("pageerror",error=>exceptions.push(error.message));
  const historyRequests:string[]=[];page.on("request",request=>{if(request.url().includes("/market/company/TEST/history"))historyRequests.push(request.url());});
  await page.setViewportSize({width:1440,height:1000});await page.goto("/companies/TEST");
  const chart=page.getByRole("region",{name:"TEST technical chart"});
  await expect(chart.locator("canvas")).toBeVisible();
  await expect(chart.getByRole("button",{name:"Candles",exact:true})).toHaveAttribute("aria-pressed","true");
  await expect(chart.getByText(/includes demo or synthetic/)).toBeVisible();
  await chart.screenshot({path:"test-results/technical-candles.png"});
  await chart.locator("summary").click();
  await chart.getByLabel("MA20",{exact:true}).check();
  await chart.getByLabel("Bollinger Bands (20, 2)").check();
  await chart.getByLabel("MACD (12, 26, 9)").check();
  await chart.getByLabel("Volume MA20").check();
  await chart.getByLabel("Show technical signals").check();
  await chart.locator("summary").click();
  await chart.getByRole("button",{name:"3M",exact:true}).click();
  await expect(chart.locator("canvas")).toBeVisible();
  await chart.screenshot({path:"test-results/technical-macd.png"});
  const canvas=chart.locator("canvas");const rect=await canvas.boundingBox();
  await page.mouse.move(rect!.x+rect!.width*.45,rect!.y+rect!.height*.3);
  await expect(chart.getByText("Open",{exact:true})).toBeVisible();
  await expect(chart.locator("span").filter({hasText:/^Volume$/})).toBeVisible();
  await page.mouse.wheel(0,-200);
  await chart.getByRole("button",{name:"Line",exact:true}).click();
  await expect(chart.getByRole("button",{name:"3M",exact:true})).toHaveAttribute("aria-pressed","true");
  await chart.locator("summary").click();await expect(chart.getByLabel("MA20",{exact:true})).toBeChecked();
  await chart.getByLabel("RSI (14)").check();await expect(chart.getByLabel("MACD (12, 26, 9)")).not.toBeChecked();
  await chart.locator("summary").click();await chart.getByRole("button",{name:"Reset zoom"}).click();
  await expect.poll(()=>historyRequests.length).toBeGreaterThanOrEqual(2);
  const rangeRequests=historyRequests.filter(url=>new URL(url).searchParams.has("end_date"));
  expect(rangeRequests.length).toBeGreaterThanOrEqual(2);
  expect(rangeRequests.every(url=>new URL(url).searchParams.has("start_date"))).toBe(true);
  await chart.getByRole("button",{name:"MAX",exact:true}).click();
  await expect(chart.locator("canvas")).toBeVisible();
  await expect(chart.getByText(/2,000 observations/)).toBeVisible();
  expect(exceptions).toEqual([]);
});
test("mobile controls and chart fit without horizontal overflow",async({page})=>{
  await page.setViewportSize({width:390,height:844});await page.goto("/companies/TEST");
  const chart=page.getByRole("region",{name:"TEST technical chart"});await expect(chart.locator("canvas")).toBeVisible();
  await chart.locator("summary").click();await chart.getByLabel("Stochastic (14, 3, 3)").check();await chart.locator("summary").click();
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await chart.screenshot({path:"test-results/technical-mobile.png"});
});
