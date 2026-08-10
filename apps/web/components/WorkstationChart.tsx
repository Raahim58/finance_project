"use client";

import ReactECharts from "echarts-for-react";

const axis = { axisLine:{lineStyle:{color:"#c8d1d8"}}, axisTick:{show:false}, axisLabel:{color:"#687786",fontSize:10}, splitLine:{lineStyle:{color:"#e8ecef"}} };

export function LineChart({labels,values,height=280,color="#244e70",percent=false}:{labels:string[];values:number[];height?:number;color?:string;percent?:boolean}) {
  if(values.length<2) return <div className="empty-state" style={{height}}><strong>History unavailable</strong><span>Add sufficient dated observations to display a trajectory.</span></div>;
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{animationDuration:350,grid:{left:46,right:14,top:18,bottom:28},tooltip:{trigger:"axis",valueFormatter:(value:number)=>percent?`${value.toFixed(2)}%`:new Intl.NumberFormat("en-PK").format(value)},xAxis:{...axis,type:"category",boundaryGap:false,data:labels,axisLabel:{...axis.axisLabel,hideOverlap:true}},yAxis:{...axis,type:"value",axisLabel:{...axis.axisLabel,formatter:percent?"{value}%":"{value}"}},series:[{type:"line",data:values,symbol:"none",lineStyle:{width:2,color},areaStyle:{color:"rgba(36,78,112,.07)"}}]}}/>;
}

export function BarChart({labels,values,height=280,horizontal=false,color="#244e70",percent=false}:{labels:string[];values:number[];height?:number;horizontal?:boolean;color?:string;percent?:boolean}) {
  if(!values.length) return <div className="empty-state" style={{height}}><strong>No observations</strong><span>This view will populate when data is available.</span></div>;
  const category={...axis,type:"category",data:labels,axisLabel:{...axis.axisLabel,interval:0,hideOverlap:true}};
  const value={...axis,type:"value",axisLabel:{...axis.axisLabel,formatter:percent?"{value}%":"{value}"}};
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{animationDuration:300,grid:{left:horizontal?76:46,right:14,top:16,bottom:horizontal?22:40,containLabel:false},tooltip:{trigger:"axis",axisPointer:{type:"shadow"},valueFormatter:(v:number)=>percent?`${v.toFixed(2)}%`:new Intl.NumberFormat("en-PK").format(v)},xAxis:horizontal?value:category,yAxis:horizontal?category:value,series:[{type:"bar",data:values,itemStyle:{color,borderRadius:0},barMaxWidth:24}]}}/>;
}

export function DonutChart({labels,values,height=250}:{labels:string[];values:number[];height?:number}) {
  if(!values.length) return <div className="empty-state" style={{height}}><strong>Allocation unavailable</strong><span>Add holdings to see the portfolio mix.</span></div>;
  const colors=["#17324d","#2d6385","#4e8994","#76a99d","#bd9d62","#9b6857","#81909b"];
  return <ReactECharts notMerge lazyUpdate style={{height,width:"100%"}} option={{color:colors,tooltip:{trigger:"item",formatter:"{b}: {d}%"},legend:{type:"scroll",orient:"vertical",right:0,top:"middle",textStyle:{fontSize:10,color:"#526170"}},series:[{type:"pie",radius:["52%","78%"],center:["36%","50%"],avoidLabelOverlap:true,label:{show:false},data:labels.map((name,i)=>({name,value:values[i]}))}]}}/>;
}
