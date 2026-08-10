"use client";
import { BarChart } from "@/components/WorkstationChart";
export function QuantChart({labels,values,title}:{labels:string[];values:number[];title:string}) { return <section className="panel"><div className="panel-head"><h2 className="panel-title">{title}</h2></div><div className="panel-body"><BarChart labels={labels} values={values}/></div></section>; }
