"use client";
import {FormEvent,useEffect,useState} from "react";
import {useAssistantWorkspace} from "@/components/AssistantWorkspace";
import styles from "./workspace.module.css";
export {styles};
import {display} from "./formatting";
export {human,display,money,date} from "./formatting";
export function Empty({title="No records returned",text="Data for this section is unavailable."}:{title?:string;text?:string}){return <div className={styles.empty}><strong>{title}</strong>{text}</div>}
export function Ask({questions=[],context=""}:{questions?:string[];context?:string}){const assistant=useAssistantWorkspace();const [question,setQuestion]=useState("");function ask(text:string){assistant?.open(context?`${text}\n${context}`:text)}function submit(event:FormEvent){event.preventDefault();if(question.trim())ask(question.trim())}return <><div className={styles.questions}>{questions.map(text=><button key={text} onClick={()=>ask(text)}>↳ {text}</button>)}</div><form className={styles.composer} onSubmit={submit}><textarea aria-label="Ask about this evidence" placeholder="Ask anything…" value={question} onChange={event=>setQuestion(event.target.value)}/><button aria-label="Open question in Assistant" disabled={!question.trim()||!assistant}>↑</button></form></>}
export function RailHeader({title}:{title:string}){return <div className={styles.rightHeader}><h2>{title}</h2></div>}
export function Details({rows}:{rows:Array<[string,unknown]>}){return <dl className={styles.detail}>{rows.map(([label,value])=><div key={label} style={{display:"contents"}}><dt>{label}</dt><dd>{display(value)}</dd></div>)}</dl>}
export function exportCsv(name:string,rows:string[][]){const text=rows.map(row=>row.map(cell=>`"${cell.replaceAll('"','""')}"`).join(",")).join("\r\n");const url=URL.createObjectURL(new Blob([text],{type:"text/csv;charset=utf-8"}));const anchor=document.createElement("a");anchor.href=url;anchor.download=name;anchor.click();URL.revokeObjectURL(url)}

export function AssistantScope({portfolioId}:{portfolioId?:string|null}){const setScope=useAssistantWorkspace()?.setPortfolioScope;useEffect(()=>{setScope?.(portfolioId||null)},[setScope,portfolioId]);return null}
