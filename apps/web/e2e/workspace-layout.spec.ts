import {expect,test} from "@playwright/test";
// Offline UI contracts only. These fixtures are never persisted as market facts.
const portfolio={id:"layout-p1",name:"Layout test portfolio",base_currency:"PKR",is_default:true,archived_at:null,source_mode:"manual",history_complete:true,selected_ips_version_id:null};
const companies=[{id:"ffc",symbol:"FFC",name:"Fauji Fertilizer",sector:"Fertilizer",is_active:true,exchange:{code:"PSX"}},{id:"efert",symbol:"EFERT",name:"Engro Fertilizers",sector:"Fertilizer",is_active:true,exchange:{code:"PSX"}},{id:"sys",symbol:"SYS",name:"Systems",sector:"Technology",is_active:true,exchange:{code:"PSX"}}];
const prices=companies.map((company,i)=>({symbol:company.symbol,open:"499",high:"502",low:"498",close:String(500+i),previous_close:"499",change:"1",change_percent:"0.2",volume:1000-i*100,value:"500000",trade_date:"2026-10-08",source:"Offline UI fixture",ingested_at:"2026-10-08T00:00:00Z"}));
const history=Array.from({length:60},(_,i)=>({...prices[0],trade_date:new Date(Date.UTC(2026,7,i+1)).toISOString().slice(0,10)}));
const summary={portfolio,total_value:"1000",cost_basis:"900",unrealized_gain_loss:"100",unrealized_gain_loss_percent:"11.1",day_change:"1",day_change_percent:"0.1",cash_balance:"750",holdings:[{symbol:"FFC",company_name:"Fauji Fertilizer",sector:"Fertilizer",quantity:"0.5",average_cost:"450",latest_price:"500",latest_price_date:"2026-10-08",market_value:"250",cost_basis:"225",unrealized_gain_loss:"25",unrealized_gain_loss_percent:"11.1",data_source:"Offline UI fixture"}],valuation_complete:true,unpriced_symbols:[],data_source:"Offline UI fixture",data_freshness_date:"2026-10-08"};
test.beforeEach(async({page})=>{
 await page.addInitScript(()=>localStorage.setItem("psx_ai_token",`offline.${btoa(JSON.stringify({sub:"layout-tester"}))}.test`));
 await page.route("**/api/**",async route=>{const url=new URL(route.request().url()),path=url.pathname.replace(/^\/api/,"");let body:unknown=[];
  if(path==="/auth/me")body={id:"layout-tester",full_name:"Layout tester",email:"layout@example.test"};
  else if(path==="/portfolios")body=[portfolio];
  else if(path.endsWith("/summary"))body=summary;
  else if(path.endsWith("/risk-flags"))body={flags:[]};
  else if(path.endsWith("/ips/compliance"))body={status:"NOT_EVALUATED",checks:[],violations:[],not_evaluated:[]};
  else if(path==="/market/companies"||path==="/instruments")body=companies;
  else if(path==="/market/company/FFC")body={company:companies[0],latest_price:prices[0]};
  else if(path.includes("/company/")&&path.endsWith("/history"))body=history;
  else if(path.includes("/index/")&&path.endsWith("/history"))body=history.map(row=>({trade_date:row.trade_date,close:"150000"}));
  else if(path==="/market/trends")body={FFC:["498","500"]};
  else if(path==="/market/overview")body={prices,trade_date:"2026-10-08",price_basis:"daily",priced_securities:3,snapshot:{snapshot_date:"2026-10-08",index_name:"KSE-100",index_value:"150000",index_change:"10",index_change_percent:"0.01",total_volume:10000,total_value:"1000000",source:"Offline UI fixture"},top_gainers:prices,top_losers:[],top_volume:prices,sectors:[{sector:"Fertilizer",trade_date:"2026-10-08",average_change_percent:"0.2",advancers:2,decliners:0,unchanged:0,total_volume:1900,total_value:"950000",source:"Offline UI fixture"}]};
  else if(path==="/market/freshness")body={market_data_mode:"mock",is_stale:false,latest_trade_date:"2026-10-08",exchange_session_status:"closed",exchange_session_note:"Offline fixture"};
  else if(path==="/macro/regime")body={regime:"not_evaluated",dimensions:{},method_note:"Offline fixture"};
  else if(path==="/research/event-feed")body={events:[],next_cursor:null};
  else if(path.endsWith("/event-intelligence"))body={portfolio_id:portfolio.id,portfolio_name:portfolio.name,events:[],valuation_complete:true,coverage:{holdings:1,priced_holdings:1}};
  else if(path.endsWith("/overview"))body={instrument:{id:"ffc",symbol:"FFC"},fundamentals:[],portfolio_relevance:[],derived_fundamentals:{ratios:{}},context:{sections:{}},has_synthetic_data:false};
  else if(path.endsWith("/intelligence"))body={symbol:"FFC",events:[],reports:[]};
  else if(path.includes("/digest"))body={status:"provider_unavailable",brief:null,prepared_intelligence:[]};
  else if(path.endsWith("/completeness"))body={price:{available:true,observations:60}};
  else if(path==="/settings/preferences")body={default_llm_provider:"zai",notification_preferences:{}};
  else if(path==="/assistant/workspace/conversations")body={items:[{id:"c1",title:"Saved layout chat",latest_activity:"2026-10-08T00:00:00Z"}],next_cursor:null};
  else if(path.startsWith("/assistant/workspace/conversations/"))body={items:[],runs:[],next_cursor:null,active_run:null,summary:null,summary_failure:null};
  await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(body)});
 });
});
test("Markets swaps its brief for stock and searchable sector detail",async({page})=>{
 await page.setViewportSize({width:1440,height:1000});await page.goto("/markets");
 const header=page.locator(".app-topbar");await expect(header.getByRole("heading",{name:"Markets",exact:true})).toBeVisible();
 await expect(header.getByRole("button",{name:"All stocks",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Search stocks and sectors"})).toHaveCount(0);
 await header.getByRole("button",{name:"All stocks",exact:true}).click();
 await page.getByRole("row").filter({hasText:"Fauji Fertilizer"}).getByRole("button",{name:"FFC",exact:true}).click();
 const stock=page.getByRole("complementary",{name:"FFC market detail"});await expect(stock.getByText("25.00%",{exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"Market brief",exact:true})).toHaveCount(0);
 await expect(stock.getByRole("link",{name:"Open company"})).toHaveAttribute("href","/companies/FFC");
 await page.screenshot({path:"test-results/layout-markets-company.png",fullPage:true});
 await stock.getByRole("button",{name:"Close market detail"}).click();await expect(page.getByRole("heading",{name:"Market brief",exact:true})).toBeVisible();
 await header.getByRole("button",{name:"Sectors",exact:true}).click();await page.getByRole("button",{name:"Fertilizer",exact:true}).click();
 const sector=page.getByRole("complementary",{name:"Fertilizer sector detail"});await expect(sector.getByText("25.00%",{exact:true})).toBeVisible();
 await sector.getByLabel("Search companies in Fertilizer").fill("Engro");await expect(sector.getByRole("button",{name:/EFERT/})).toBeVisible();await expect(sector.getByRole("button",{name:/FFC/})).toHaveCount(0);
 await sector.getByLabel("Search companies in Fertilizer").fill("");await page.screenshot({path:"test-results/layout-markets-sector.png",fullPage:true});
});
test("company sidebar retains its separate simple chart",async({page})=>{
 await page.goto("/companies/FFC");const history=page.getByLabel("FFC sidebar price history",{exact:true});await expect(history.locator("canvas")).toBeVisible();
 await expect(page.getByRole("region",{name:"FFC technical chart"}).locator("canvas")).toBeVisible();
 await expect(page.locator(".app-topbar").getByRole("button",{name:"Fundamentals",exact:true})).toBeVisible();
 await page.screenshot({path:"test-results/layout-company.png",fullPage:true});
});
test("oversight pages share title and tabs in the header",async({page})=>{
 for(const [path,title] of [["/recommendations","Recommendations"],["/monitoring","Monitoring"],["/activity","Activity"]]){
  await page.goto(path);await expect(page.locator(".app-topbar").getByRole("heading",{name:title,exact:true})).toBeVisible();
  await expect(page.locator("main h1")).toHaveCount(0);await page.screenshot({path:`test-results/layout-${title.toLowerCase()}.png`,fullPage:true});
 }
 await page.goto("/monitoring");await expect(page.locator(".app-topbar").getByRole("button",{name:"Acknowledged",exact:true})).toBeVisible();
});
test("management replaces the legacy grid and opens inline creation",async({page})=>{
 await page.goto("/portfolios/manage?create=1");await expect(page.getByLabel("Portfolio name",{exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Create and define IPS",exact:true})).toBeVisible();
 await expect(page.getByText("1 Investor profile",{exact:true})).toHaveCount(0);await expect(page.getByRole("button",{name:"Layout test portfolio",exact:true})).toBeVisible();
 await page.screenshot({path:"test-results/layout-portfolios.png",fullPage:true});
});
test("full chat fills the workspace and floating Ask opens and closes cleanly",async({page})=>{
 await page.setViewportSize({width:1440,height:1000});await page.goto("/assistant");
 const chat=page.getByRole("region",{name:"Assistant",exact:true});await expect(chat).toBeVisible();
 const bounds=await chat.boundingBox();expect(bounds!.width).toBeGreaterThan(1100);expect(bounds!.y).toBe(60);
 await expect(page.getByRole("button",{name:"Open Assistant",exact:true})).toHaveCount(0);
 const selected=page.locator(".assistant-conversation-list button[aria-current='true']");
 await expect(selected).toBeVisible();
 const painted=await selected.evaluate(element=>{const style=getComputedStyle(element);return {background:style.backgroundColor,shadow:style.boxShadow,before:getComputedStyle(element,"::before").content}});
 expect(painted.background).toBe("rgba(0, 0, 0, 0)");expect(painted.shadow).toBe("none");expect(painted.before).toBe("none");
 await page.screenshot({path:"test-results/layout-chat.png",fullPage:true});
 await page.goto("/monitoring");await page.getByRole("button",{name:"Open Assistant",exact:true}).click();await expect(page.getByRole("dialog",{name:"Assistant",exact:true})).toBeVisible();
 await expect(page.getByRole("button",{name:"Open Assistant",exact:true})).not.toBeVisible();await page.getByRole("button",{name:"Close Assistant",exact:true}).click();await expect(page.getByRole("button",{name:"Open Assistant",exact:true})).toBeVisible();
});
test("shared header and chat fit on mobile",async({page})=>{
 await page.setViewportSize({width:390,height:844});
 for(const path of ["/markets","/monitoring","/portfolios/manage","/assistant"]){await page.goto(path);await expect(page.locator(".app-topbar")).toBeVisible();await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);}
 await page.screenshot({path:"test-results/layout-mobile-chat.png",fullPage:true});
});
