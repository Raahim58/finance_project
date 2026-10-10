import {expect,test} from "@playwright/test";
// Offline UI fixtures; these responses never enter the deployed database.
const evidence={id:"chunk:fixture",document_id:"fixture-doc",page_number:7,title:"Offline UI test evidence",source_name:"Test fixture",source_url:"https://example.test/fixture.pdf",text:"The fixture company reports floating-rate financing exposure."};
const event={id:"fixture-event",event_key:"raw:fixture-event",raw_event_id:"fixture-event",normalized_event_id:"fixture-normalized",title:"Offline fixture: SBP monetary policy decision",occurred_at:"2026-08-12T00:00:00Z",event_type:"rates",source_document_type:"news",materiality:"high",freshness_status:"recent",factors:["pk_policy_rate"],subjects:[],relationship_kind:"ai_proposed_indirect",evidence:[evidence],saved_brief:null};
const portfolio={id:"fixture-portfolio",name:"Offline test portfolio",is_default:true,archived_at:null};
const personal={portfolio_id:portfolio.id,portfolio_name:portfolio.name,events:[{event,companies:[{symbol:"AAA",relationship_kind:"ai_proposed_indirect",saved_brief:null,current_portfolio_weight:"0.25"}],potentially_affected_weight:"0.25"}],valuation_complete:true,coverage:{holdings:1,priced_holdings:1}};
const company={instrument_id:"fixture-instrument",symbol:"AAA",events:[event],reports:[],profile:null};
const context={instrument:{id:"fixture-instrument",symbol:"AAA"},fundamentals:[],events:[],documents:[],market_research:null,derived_fundamentals:null,portfolio_relevance:[],context:{sections:{}},has_synthetic_data:false,refresh_request_id:null};
test.beforeEach(async({page})=>{
 let selectedId=portfolio.id;
 await page.addInitScript(()=>localStorage.setItem("psx_ai_token","offline-browser-test-token"));
 await page.route("**/api/**",async route=>{
  const url=new URL(route.request().url());const path=url.pathname.replace(/^\/api/,"");
  let body:unknown=[];
  if(path==="/auth/me")body={id:"fixture-user",email:"fixture@example.test",full_name:"Offline UI tester"};
  else if(path==="/portfolios")body=[portfolio,{...portfolio,id:"second-portfolio",name:"Second test portfolio"}].map(row=>({...row,is_default:row.id===selectedId}));
  else if(path.endsWith("/select-default")){selectedId=path.split("/")[2];body={...portfolio,id:selectedId,is_default:true};}
  else if(path.endsWith("/summary"))body={portfolio:{...portfolio,id:path.split("/")[2]},holdings:[{symbol:"AAA",company_name:"Offline fixture company",sector:"Test sector",quantity:"10",market_value:path.includes("second-portfolio")?"500":"250"}],total_value:"1000",cash_balance:"750",valuation_complete:true};
  else if(path==="/documents")body=[{id:"fixture-doc",title:evidence.title,symbol:"AAA",document_type:"annual_report",source_name:evidence.source_name,source_url:evidence.source_url,status:"ready",data_status:"observed",published_date:"2026-08-12",created_at:"2026-08-12T00:00:00Z"}];
  else if(path==="/research/event-feed")body={events:[event],next_cursor:null};
  else if(path.endsWith("/event-intelligence"))body=path.includes("second-portfolio")?{...personal,portfolio_id:"second-portfolio",portfolio_name:"Second test portfolio",events:personal.events.map(row=>({...row,potentially_affected_weight:"0.50"}))}:personal;
  else if(path==="/research/companies/AAA/intelligence")body=company;
  else if(path==="/research/instruments"||path==="/instruments"||path==="/market/companies"||path.endsWith("/search"))body=[{id:"fixture-instrument",symbol:"AAA",name:"Offline fixture company"}];
  else if(path==="/market/company/AAA")body={company:{symbol:"AAA",name:"Offline fixture company",sector:"Test sector",exchange:{code:"PSX"}},latest_price:{close:"100",change_percent:"1",trade_date:"2026-08-12",source:"Test fixture"}};
  else if(path.endsWith("/completeness"))body={price:{available:true,observations:1},fundamentals:{available:false,fact_count:0},reports:{available:false,count:0},announcements:{available:false,count:0},news:{available:false,count:0}};
  else if(path.endsWith("/overview"))body=context;
  else if(path==="/research/batches/preview")body={companies:[{instrument_id:"fixture-instrument",symbol:"AAA",reports_to_index:0,profile_cached:false,digest_cached:false,selected_events:1,max_calls:2}],maximum_calls:2,budget_calls:16,within_budget:true,provider_config:null,estimated_input_tokens_upper_bound:18000,estimated_output_tokens_upper_bound:4000};
  else if(path==="/documents/fixture-doc/pages/7")body={title:evidence.title,page_number:7,text:evidence.text};
  await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
 });
});
test("research hub has market and selected portfolio events without generation on load",async({page})=>{
 const generation:string[]=[];page.on("request",r=>{if(r.method()==="POST"&&r.url().includes("/research/batches"))generation.push(r.url())});
 await page.goto("/research");await page.getByRole("tab",{name:"Events",exact:true}).click();await expect(page.getByRole("button",{name:event.title,exact:true})).toBeVisible();expect(generation).toEqual([]);
 await page.getByRole("button",{name:"Find a company",exact:true}).click();await page.getByRole("textbox",{name:"Find a company",exact:true}).fill("AAA");await expect(page.getByRole("link",{name:"AAA Offline fixture company"})).toHaveAttribute("href","/companies/AAA");await page.getByRole("textbox",{name:"Find a company",exact:true}).press("Escape");
 await page.goto(`/portfolios/${portfolio.id}/research`);await page.getByRole("tab",{name:"Events",exact:true}).click();await expect(page.getByText("25.00%",{exact:true})).toBeVisible();
 await page.getByRole("button",{name:"Preview generation"}).click();await expect(page.getByText("Save an active AI key in Settings first.")).toBeVisible();await expect(page.getByRole("button",{name:"Generate saved explanations"})).toBeDisabled();expect(generation).toHaveLength(1);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:"test-results/research-hub.png",fullPage:true});
});
test("source page drawer opens from event evidence on mobile",async({page})=>{
 await page.setViewportSize({width:390,height:844});await page.goto("/research");await page.getByRole("tab",{name:"Events",exact:true}).click();await page.getByRole("button",{name:"Read page 7"}).first().click();await expect(page.getByRole("dialog",{name:"Source page"})).toBeVisible();await expect(page.getByRole("dialog").getByText(evidence.text)).toBeVisible();await page.getByRole("button",{name:"Close",exact:true}).click();await expect(page.getByRole("dialog")).not.toBeVisible();
 await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test("unheld company page separates company analysis and selected portfolio relevance",async({page})=>{
 const paid:string[]=[];page.on("request",r=>{if(r.method()==="POST")paid.push(r.url())});
 await page.goto("/companies/AAA");
 await page.getByRole("button",{name:"Events",exact:true}).click();await expect(page.getByRole("heading",{name:"What changed"})).toBeVisible();
 await expect(page.getByText("Not held in this selected portfolio.").first()).toBeVisible();
 await expect(page.getByRole("button",{name:"Analyze company",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Analyze selected portfolio relevance",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Reports",exact:true})).toBeVisible();
 expect(paid).toEqual([]);
});

test("market exposure follows the research portfolio selector",async({page})=>{
 await page.goto(`/portfolios/${portfolio.id}/research`);await page.getByRole("tab",{name:"Events",exact:true}).click();
 await expect(page.getByText("25.00%",{exact:true})).toBeVisible();
 await page.getByRole("combobox",{name:/^Selected portfolio/}).selectOption("second-portfolio");
 await expect(page).toHaveURL(/\/portfolios\/second-portfolio\/research$/);await page.getByRole("tab",{name:"Events",exact:true}).click();
 await expect(page.getByText("50.00%",{exact:true})).toBeVisible();
 await expect(page.getByText("25.00%",{exact:true})).toHaveCount(0);
});
