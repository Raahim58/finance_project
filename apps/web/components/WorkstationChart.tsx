"use client";

import ReactECharts from "echarts-for-react";

const ink = "#171a1d";
const muted = "#73787d";
const green = "#126b52";
const axis = {
  axisLine: { lineStyle: { color: "rgba(23,26,29,.12)" } },
  axisTick: { show: false },
  axisLabel: { color: muted, fontSize: 11, fontFamily: "Inter, ui-sans-serif, system-ui" },
  splitLine: { lineStyle: { color: "rgba(23,26,29,.06)" } },
};
const base = {
  animationDuration: 220,
  textStyle: { color: ink, fontFamily: "Inter, ui-sans-serif, system-ui" },
  aria: { enabled: true },
  tooltip: {
    backgroundColor: "#171a1d",
    borderWidth: 0,
    padding: [9, 11],
    textStyle: { color: "#fff", fontSize: 12 },
    extraCssText: "border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12)",
  },
};

export function LineChart({labels,values,height=280,color=green,percent=false}:{labels:string[];values:number[];height?:number;color?:string;percent?:boolean}) {
  if(values.length<2) return <div className="empty-state" style={{height}}><strong>History unavailable</strong><span>Add sufficient dated observations to display a trajectory.</span></div>;
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{...base,grid:{left:18,right:18,top:18,bottom:20,containLabel:true},tooltip:{...base.tooltip,trigger:"axis",valueFormatter:(value:number)=>percent?`${value.toFixed(2)}%`:new Intl.NumberFormat("en-PK").format(value)},xAxis:{...axis,type:"category",boundaryGap:false,data:labels,axisLabel:{...axis.axisLabel,hideOverlap:true}},yAxis:{...axis,type:"value",axisLabel:{...axis.axisLabel,formatter:percent?"{value}%":"{value}"}},series:[{type:"line",data:values,symbol:"none",smooth:.12,lineStyle:{width:2.5,color},areaStyle:{color:"rgba(18,107,82,.055)"},emphasis:{lineStyle:{width:3}}}]}}/>;
}

export function BarChart({labels,values,height=280,horizontal=false,color=green,percent=false}:{labels:string[];values:number[];height?:number;horizontal?:boolean;color?:string;percent?:boolean}) {
  if(!values.length) return <div className="empty-state" style={{height}}><strong>No observations</strong><span>This view will populate when data is available.</span></div>;
  const category={...axis,type:"category",data:labels,axisLabel:{...axis.axisLabel,interval:0,hideOverlap:true}};
  const value={...axis,type:"value",axisLabel:{...axis.axisLabel,formatter:percent?"{value}%":"{value}"}};
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{...base,grid:{left:14,right:18,top:14,bottom:22,containLabel:true},tooltip:{...base.tooltip,trigger:"axis",axisPointer:{type:"shadow",shadowStyle:{color:"rgba(23,26,29,.035)"}},valueFormatter:(v:number)=>percent?`${v.toFixed(2)}%`:new Intl.NumberFormat("en-PK").format(v)},xAxis:horizontal?value:category,yAxis:horizontal?category:value,series:[{type:"bar",data:values,itemStyle:{color,borderRadius:horizontal?[0,4,4,0]:[4,4,0,0]},barMaxWidth:22}]}}/>;
}

export function DonutChart({labels,values,height=250}:{labels:string[];values:number[];height?:number}) {
  if(!values.length) return <div className="empty-state" style={{height}}><strong>Allocation unavailable</strong><span>Add holdings to see the portfolio mix.</span></div>;
  const colors=["#126b52","#39826b","#69a18e","#9bbcaf","#536b70","#8e7959","#a9aea9"];
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{...base,color:colors,tooltip:{...base.tooltip,trigger:"item",formatter:"{b}<br/><strong>{d}%</strong>"},legend:{type:"scroll",orient:"vertical",right:0,top:"middle",itemWidth:9,itemHeight:9,itemGap:12,textStyle:{fontSize:11,color:muted}},series:[{type:"pie",radius:["58%","80%"],center:["34%","50%"],avoidLabelOverlap:true,padAngle:1,itemStyle:{borderColor:"#fff",borderWidth:2,borderRadius:2},label:{show:false},data:labels.map((name,i)=>({name,value:values[i]}))}]}}/>;
}

export function ScatterChart({
  points,
  height=320,
  xName,
  yName,
  percentAxes=false,
  xPercent,
  yPercent,
  seriesName="Series",
}:{
  points:Array<{x:number;y:number;name?:string}>;
  height?:number;
  xName:string;
  yName:string;
  percentAxes?:boolean;
  xPercent?:boolean;
  yPercent?:boolean;
  seriesName?:string;
}) {
  if(!points.length) return <div className="empty-state" style={{height}}><strong>Series unavailable</strong><span>The model did not return chart-ready observations.</span></div>;
  const format=(value:number,asPercent:boolean)=>asPercent?`${(value*100).toFixed(1)}%`:value.toFixed(2);
  const xp=xPercent??percentAxes,yp=yPercent??percentAxes;
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{...base,grid:{left:18,right:20,top:20,bottom:18,containLabel:true},tooltip:{...base.tooltip,trigger:"item",formatter:(p:{data:{value:number[];name?:string}})=>`${p.data.name??seriesName}<br/>${xName}: ${format(p.data.value[0],xp)}<br/>${yName}: ${format(p.data.value[1],yp)}`},xAxis:{...axis,type:"value",name:xName,nameLocation:"middle",nameGap:34,nameTextStyle:{color:muted,fontSize:11},axisLabel:{...axis.axisLabel,formatter:(value:number)=>format(value,xp)}},yAxis:{...axis,type:"value",name:yName,nameGap:44,nameLocation:"middle",nameTextStyle:{color:muted,fontSize:11},axisLabel:{...axis.axisLabel,formatter:(value:number)=>format(value,yp)}},series:[{name:seriesName,type:"scatter",symbolSize:10,itemStyle:{color:green,borderColor:"#fff",borderWidth:1.5},emphasis:{scale:1.35},data:points.map(p=>({name:p.name,value:[p.x,p.y]}))}]}}/>;
}

export function HistogramChart({bins,height=320}:{bins:Array<{lower:number;upper:number;count:number}>;height?:number}) {
  return <BarChart height={height} labels={bins.map(bin=>`${(bin.lower*100).toFixed(1)}–${(bin.upper*100).toFixed(1)}%`)} values={bins.map(bin=>bin.count)} color="#536b70"/>;
}
