"use client";
import { useState, useRef, useEffect } from "react";
import { useAssistantWorkspace } from "./AssistantWorkspace";
import { Icon } from "./Icon";

export function AssistantControls() {
  const workspace = useAssistantWorkspace();
  const [historyOpen, setHistoryOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!historyOpen) return;
    const dismiss = (event: PointerEvent) => { if (!box.current?.contains(event.target as Node)) setHistoryOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setHistoryOpen(false); };
    document.addEventListener("pointerdown", dismiss); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", dismiss); document.removeEventListener("keydown", escape); };
  }, [historyOpen]);
  if (!workspace) return null;
  return <div className="market-ask-controls" ref={box}>
    <button className="market-ask-button" aria-label={workspace.opened ? "Close Assistant sidebar" : "Open Assistant sidebar"} aria-expanded={workspace.opened} onClick={() => workspace.opened ? workspace.close() : workspace.open()}><span aria-hidden="true">✦</span> Ask</button>
    <button className="market-history-toggle" aria-label="Previous chats" aria-haspopup="true" aria-expanded={historyOpen} onClick={() => setHistoryOpen(!historyOpen)}><Icon name="chevron" size={14} /></button>

    {historyOpen ? <div className="market-chat-menu" role="region" aria-label="Previous conversations">
      <button onClick={() => { void workspace.newChat(); workspace.open(); setHistoryOpen(false); }}>＋ New chat</button>
      {workspace.chats.map(chat => <button key={chat.id} aria-current={workspace.selected === chat.id ? "true" : undefined} onClick={() => { workspace.selectChat(chat.id); setHistoryOpen(false); }}>{chat.title}<small>{chat.active_run ? "Generating" : ""}</small></button>)}
      {!workspace.chats.length ? <p>No previous chats yet.</p> : null}
      {workspace.hasMoreChats ? <button onClick={workspace.moreChats}>More chats</button> : null}
    </div> : null}
  </div>;
}
