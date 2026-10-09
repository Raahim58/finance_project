"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { formatDate } from "@/lib/overview";
import { PortfolioContextPicker } from "./PortfolioContextPicker";
import { AssistantEvidenceContext } from "./AssistantEvidenceContext";
import { usePathname } from "next/navigation";
import { AssistantProviderSwitch } from "@/components/AssistantProviderSwitch";
import {
  ChatMessageView,
  Markdown,
  outcomeLabel,
} from "@/components/AssistantChatMessage";
import {
  getPortfolios,
  getToken,
  searchInstruments,
  type AssistantResult,
} from "@/lib/api";
import {
  createChat,
  continueChat,
  getHistory,
  listChats,
  observeRun,
  retrySummary,
  stopRun,
  submitRun,
  type ChatMessage,
  type ChatRun,
  type Conversation,
  type History,
  type MessageContext,
  sumTokenUsage,
  type RunEvent,
} from "@/lib/assistant-workspace";

type LiveRun = ChatRun & {
  conversationId: string;
  text: string;
  activity: string;
  sequence: number;
  warning?: string;
};
type WorkspaceAction = {
  open: (question?: string) => void; setCompanyPortfolioScope: (id: string | null) => void; setPortfolioScope: (id: string | null) => void; close: () => void; opened: boolean;
  chats: Conversation[]; selected: string | null; selectChat: (id: string) => void;
  newChat: () => Promise<string | null>; moreChats: () => void; hasMoreChats: boolean;
};
const Workspace = createContext<WorkspaceAction | null>(null);
export function useAssistantWorkspace() {
  return useContext(Workspace);
}
export function AskAssistant({
  question,
  children,
}: {
  question: string;
  children: React.ReactNode;
}) {
  const workspace = useAssistantWorkspace();
  return (
    <button
      type="button"
      className="btn btn-secondary"
      onClick={() => workspace?.open(question)}
    >
      {children}
    </button>
  );
}
const active = (status: string) => status === "queued" || status === "running";
function accountIdentity() {
  const token = getToken();
  if (!token) return null;
  try {
    return String(
      JSON.parse(
        atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
      ).sub,
    );
  } catch {
    return token;
  }
}

export function AssistantWorkspaceProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const fullPage = pathname === "/assistant";
  const [assistantCompany,setAssistantCompany] = useState<{id:string;symbol:string;name:string}|null>(null);
  const [companyChoices,setCompanyChoices] = useState<Array<{id:string;symbol:string;name:string}>>([]);
  useEffect(()=>{if(!fullPage)return;let active=true;void searchInstruments().then(rows=>{if(active)setCompanyChoices(rows)}).catch(()=>{if(active)setCompanyChoices([])});return()=>{active=false};},[fullPage]);
  const [scopeRevision, setScopeRevision] = useState(0);
  const [companyPortfolioScope, setCompanyPortfolioScopeState] = useState<{path:string;id:string|null}|null>(null);
  const setCompanyPortfolioScope = useCallback((id:string|null) => {
    setCompanyPortfolioScopeState(old => old?.path===pathname&&old.id===id?old:{path:pathname,id});
  },[pathname]);
  useEffect(() => {
    const changed = () => setScopeRevision(value => value + 1);
    window.addEventListener("psx-portfolio-change", changed);
    return () => window.removeEventListener("psx-portfolio-change", changed);
  }, []);
  const [account, setAccount] = useState<string | null>(null);
  const [launcherHidden, setLauncherHidden] = useState(false);
  useEffect(()=>{setLauncherHidden(window.localStorage.getItem("psx_ask_hidden")==="1")},[]);
  const hideLauncher=(hidden:boolean)=>{setLauncherHidden(hidden);window.localStorage.setItem("psx_ask_hidden",hidden?"1":"0")};
  const [opened, setOpened] = useState(false),
    [expanded, setExpanded] = useState(false),
    [showChats, setShowChats] = useState(false);
  const [chats, setChats] = useState<Conversation[]>([]),
    [chatCursor, setChatCursor] = useState<string | null>(null),
    [selected, setSelected] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({}),
    [histories, setHistories] = useState<Record<string, History>>({}),
    [runs, setRuns] = useState<Record<string, LiveRun>>({});
  const [context, setContext] = useState<MessageContext>({ page: "workspace" }),
    [contextReady, setContextReady] = useState(false),
    [error, setError] = useState<string | null>(null),
    [submitting, setSubmitting] = useState(false);
  const runsRef = useRef(runs),
    controllers = useRef(new Map<string, AbortController>()),
    alive = useRef(true),
    selectedRef = useRef(selected),
    accountRef = useRef(account);
  const pendingPrefill = useRef<string | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null),
    trigger = useRef<HTMLButtonElement>(null),
    dialog = useRef<HTMLElement>(null),
    scroller = useRef<HTMLDivElement>(null),
    nearBottom = useRef(true);
  const [newMessages, setNewMessages] = useState(false);
  const [provider, setProvider] = useState<string | null>(null);
  const [providerSaving, setProviderSaving] = useState(false);
  runsRef.current = runs;
  selectedRef.current = selected;
  accountRef.current = account;
  const replaceRun = useCallback(
    (id: string, update: (run: LiveRun) => LiveRun) => {
      setRuns((old) => {
        const existing = old[id];
        if (!existing) return old;
        const next = { ...old, [id]: update(existing) };
        runsRef.current = next;
        return next;
      });
    },
    [],
  );
  const loadHistory = useCallback(async (id: string, cursor?: string) => {
    const owner = accountRef.current;
    const history = await getHistory(id, cursor);
    if (owner !== accountRef.current || !alive.current) return;
    setHistories((old) => ({
      ...old,
      [id]: cursor
        ? {
            ...history,
            items: [...history.items, ...(old[id]?.items ?? [])].filter(
              (m, i, a) => a.findIndex((x) => x.id === m.id) === i,
            ),
          }
        : history,
    }));
    return history;
  }, []);
  const observe = useCallback(
    (run: ChatRun, conversationId: string) => {
      if (controllers.current.has(run.execution_id)) return;
      const owner = accountRef.current;
      const controller = new AbortController();
      controllers.current.set(run.execution_id, controller);
      setRuns((old) => {
        const next = {
          ...old,
          [run.execution_id]: old[run.execution_id] ?? {
            ...run,
            conversationId,
            text: "",
            activity: "Waiting for model",
            sequence: 0,
          },
        };
        runsRef.current = next;
        return next;
      });
      const applyTerminal = (payload: RunEvent["payload"]) => {
        if (controller.signal.aborted || owner !== accountRef.current) return;
        replaceRun(run.execution_id, (r) => ({
          ...r,
          status: payload.status ?? r.status,
          error_code: payload.error_code,
          activity: "",
        }));
        if (payload.response) {
          const response = payload.response;
          setHistories((old) => {
            const existing = old[conversationId];
            if (!existing) return old;
            const message: ChatMessage = {
              id: response.message_id,
              role: "assistant",
              content: response.answer,
              context: existing.items.find(
                (m) => m.execution_id === run.execution_id && m.role === "user",
              )?.context ?? { page: "workspace" },
              execution_id: run.execution_id,
              outcome: payload.status,
              created_at: response.created_at,
              evidence: {
                sources: response.source_citations,
                synthesis: response.synthesis,
              },
            };
            return {
              ...old,
              [conversationId]: {
                ...existing,
                items: [
                  ...existing.items.filter((m) => m.id !== message.id),
                  message,
                ],
              },
            };
          });
        }
        if (payload.status && !active(payload.status))
          void loadHistory(conversationId).catch(() => {});
      };
      void (async () => {
        while (!controller.signal.aborted) {
          try {
            await observeRun(
              run.execution_id,
              runsRef.current[run.execution_id]?.sequence ?? 0,
              controller.signal,
              (event) => {
                if (controller.signal.aborted || owner !== accountRef.current)
                  return;
                if (
                  event.sequence <=
                  (runsRef.current[run.execution_id]?.sequence ?? 0)
                )
                  return;
                replaceRun(run.execution_id, (r) => ({
                  ...r,
                  sequence: event.sequence,
                  text:
                    event.kind === "text_delta"
                      ? r.text + (event.payload.text ?? "")
                      : r.text,
                  activity:
                    event.kind === "activity"
                      ? (event.payload.text ?? r.activity)
                      : r.activity,
                  warning:
                    event.kind === "warning" ? event.payload.text : r.warning,
                }));
                if (event.kind === "terminal") applyTerminal(event.payload);
              },
              applyTerminal,
            );
            if (
              !active(runsRef.current[run.execution_id]?.status ?? "completed")
            )
              break;
          } catch {
            if (controller.signal.aborted) break;
            replaceRun(run.execution_id, (r) => ({
              ...r,
              activity: "Reconnecting…",
            }));
          }
          await new Promise<void>((resolve) => {
            const timer = setTimeout(resolve, 1000);
            controller.signal.addEventListener(
              "abort",
              () => {
                clearTimeout(timer);
                resolve();
              },
              { once: true },
            );
          });
        }
        controllers.current.delete(run.execution_id);
      })();
    },
    [loadHistory, replaceRun],
  );
  const refreshChats = useCallback(
    async (cursor?: string) => {
      const owner = accountRef.current;
      const page = await listChats(cursor);
      if (owner !== accountRef.current || !alive.current) return;
      setChats((old) =>
        cursor
          ? [...old, ...page.items].filter(
              (c, i, a) => a.findIndex((x) => x.id === c.id) === i,
            )
          : page.items,
      );
      setChatCursor(page.next_cursor);
      for (const chat of page.items)
        if (chat.active_run) observe(chat.active_run, chat.id);
      return page.items;
    },
    [observe],
  );
  useEffect(() => {
    alive.current = true;
    const changed = () => setAccount(accountIdentity());
    changed();
    window.addEventListener("psx-auth-change", changed);
    window.addEventListener("storage", changed);
    return () => {
      alive.current = false;
      window.removeEventListener("psx-auth-change", changed);
      window.removeEventListener("storage", changed);
      for (const controller of controllers.current.values()) controller.abort();
      controllers.current.clear();
    };
  }, []);
  useEffect(() => {
    for (const controller of controllers.current.values()) controller.abort();
    controllers.current.clear();
    setChats([]);
    setHistories({});
    setRuns({});
    runsRef.current = {};
    setSelected(null);
    setDrafts({});
    pendingPrefill.current = null;
    setOpened(false);
    setError(null);
    setProvider(null);
    setProviderSaving(false);
    setAssistantCompany(null);
    if (account)
      void refreshChats()
        .then((rows) => {
          if (rows?.[0]) setSelected(rows[0].id);
        })
        .catch((e) => setError(String(e.message)));
  }, [account, refreshChats]);
  useEffect(() => {
    let valid = true;
    setContextReady(false);
    setContext({ page: "workspace" });
    void (async () => {
      try {
        const portfolios = await getPortfolios();
        const portfolioId = pathname.match(/^\/portfolios\/([^/]+)/)?.[1];
        const explicitCompanyScope = companyPortfolioScope?.path===pathname;
        const requestedPortfolioId = portfolioId ?? (explicitCompanyScope ? companyPortfolioScope?.id : undefined);
        const portfolio = requestedPortfolioId
          ? portfolios.find((p) => p.id === requestedPortfolioId && !p.archived_at)
          : explicitCompanyScope ? undefined : portfolios.find((p) => p.is_default && !p.archived_at);
        const symbol = pathname.match(/^\/companies\/([^/]+)/)?.[1];
        const company = fullPage && assistantCompany ? assistantCompany : symbol
          ? (await searchInstruments(decodeURIComponent(symbol))).find(
              (c) =>
                c.symbol.toUpperCase() ===
                decodeURIComponent(symbol).toUpperCase(),
            )
          : null;
        if (valid) {
          setContext({
            page: portfolioId ? "portfolio" : company ? "company" : "workspace",
            portfolio_id: portfolio?.id,
            portfolio_name: portfolio?.name,
            instrument_id: company?.id,
            symbol: company?.symbol,
            company_name: company?.name,
            explicit_scope: !symbol && (fullPage || explicitCompanyScope || Boolean(portfolioId)),
          });
          setContextReady(!requestedPortfolioId || !!portfolio);
          if (symbol && !company) setContextReady(false);
        }
      } catch {
        if (valid) setContextReady(false);
      }
    })();
    return () => {
      valid = false;
    };
  }, [pathname, account, opened, scopeRevision, companyPortfolioScope, assistantCompany, fullPage]);
  useEffect(() => {
    if (selected)
      void loadHistory(selected)
        .then((history) => {
          if (history?.active_run) observe(history.active_run, selected);
          for (const run of history?.runs ?? [])
            if (
              !active(run.status) &&
              !history?.items.some(
                (m) =>
                  m.execution_id === run.execution_id && m.role === "assistant",
              )
            )
              observe(run, selected);
        })
        .catch((e) => setError(e.message));
  }, [selected, loadHistory, observe]);
  useEffect(() => {
    if (!opened || fullPage) return;
    const previous = document.activeElement as HTMLElement | null;
    composer.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpened(false);
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const elements = Array.from(
        dialog.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]),textarea,a[href],select",
        ),
      );
      const first = elements[0],
        last = elements.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("keydown", key);
      previous?.focus();
    };
  }, [opened, fullPage]);
  useEffect(() => {
    if (!opened && !fullPage) return;
    if (nearBottom.current) {
      const element = scroller.current;
      if (element) element.scrollTop = element.scrollHeight;
      setNewMessages(false);
    } else setNewMessages(true);
  }, [histories, runs, opened, selected, fullPage]);
  const open = useCallback((question?: string) => {
    setOpened(true);
    if (question) {
      if (!selectedRef.current) pendingPrefill.current = question;
      setDrafts((old) => ({
        ...old,
        [selectedRef.current ?? "new"]: question,
      }));
    }
  }, []);
  useEffect(() => {
    if (selected && pendingPrefill.current) {
      const question = pendingPrefill.current;
      pendingPrefill.current = null;
      setDrafts((old) => ({ ...old, [selected]: question }));
    }
  }, [selected]);
  const newChat = async () => {
    try {
      const chat = await createChat();
      setSelected(chat.id);
      setShowChats(false);
      await refreshChats();
      return chat.id;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  };
  const send = async () => {
    const key = selected ?? "new",
      question = (drafts[key] ?? "").trim();
    if (!question || submitting || providerSaving || !contextReady) return;
    setSubmitting(true);
    setError(null);
    const owner = accountRef.current;
    const snapshot = { ...context };
    try {
      const id = selected ?? (await newChat());
      if (!id) return;
      const accepted = await submitRun(
        id,
        question,
        snapshot,
        crypto.randomUUID(),
        provider ?? undefined,
      );
      if (owner !== accountRef.current) return;
      setDrafts((old) => ({ ...old, [key]: "", [id]: "" }));
      setSelected(id);
      await loadHistory(id);
      observe(accepted, id);
      void refreshChats().catch(() => {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };
  const history = selected ? histories[selected] : null,
    conversationTokens = sumTokenUsage(history?.items ?? []),
    live = Object.values(runs).filter((r) => r.conversationId === selected),
    running = live.find((r) => active(r.status)),
    draft = drafts[selected ?? "new"] ?? "";
  const suggestions = context.portfolio_id
    ? ["Explain concentration", "Review missing inputs", "What changed recently?"]
    : context.symbol
      ? [`Summarise ${context.symbol}`, `Key risks for ${context.symbol}`]
      : ["Summarise today's market", "What can you tell me about my portfolio?"];
  const prefill = (text: string) => {
    setDrafts((old) => ({ ...old, [selected ?? "new"]: text }));
    composer.current?.focus();
  };
  const marketWorkspace = !fullPage;
  const action: WorkspaceAction = { open, setCompanyPortfolioScope, setPortfolioScope:setCompanyPortfolioScope, close: () => setOpened(false), opened, chats, selected,
    selectChat: id => { setSelected(id); setOpened(true); setShowChats(false); nearBottom.current = true; },
    newChat, moreChats: () => { if (chatCursor) void refreshChats(chatCursor); }, hasMoreChats: !!chatCursor };
  return (
    <Workspace.Provider value={action}>
      {children}
      {!fullPage?(launcherHidden?<button type="button" className="assistant-launcher-tab" aria-label="Show Ask" onClick={()=>hideLauncher(false)}>‹</button>:<div className={`assistant-launcher-wrap${opened?" assistant-launcher-open":""}`}>
        <button
          ref={trigger}
          className="assistant-launcher"
          type="button"
          aria-label="Open Assistant"
          aria-expanded={opened}
          onClick={() => setOpened(!opened)}
        >
          <span aria-hidden="true">✦</span> Ask
          {Object.values(runs).some((r) => active(r.status)) ? (
            <span className="assistant-running-dot" />
          ) : null}
        </button>
        <button type="button" className="assistant-launcher-dismiss" aria-label="Hide Ask" title="Hide Ask" onClick={()=>hideLauncher(true)}>›</button>
      </div>):null}
      {opened || fullPage ? (
        <section
          ref={dialog}
          role={fullPage?"region":"dialog"}
          aria-modal={fullPage?undefined:true}
          aria-label="Assistant"
          className={`assistant-drawer${expanded && !fullPage ? " assistant-expanded" : ""}${marketWorkspace ? " assistant-market-overlay" : ""}${fullPage ? " assistant-full-page" : ""}`}
        >
          {fullPage?<aside className="assistant-conversation-list" aria-label="Conversations">
            <div><h1>Chats</h1><button type="button" onClick={()=>void newChat()}>＋ New chat</button></div>
            <nav aria-label="Saved chat threads">{chats.map(chat=><button key={chat.id} aria-current={selected===chat.id?"true":undefined} onClick={()=>{setSelected(chat.id);nearBottom.current=true;}}><strong>{chat.title}</strong><span>{chat.latest_activity?formatDate(chat.latest_activity):"—"}{chat.active_run?" · Generating":""}</span></button>)}</nav>
            {!chats.length?<p>No saved chats yet.</p>:null}{chatCursor?<button type="button" onClick={()=>void refreshChats(chatCursor)}>More chats</button>:null}
          </aside>:null}
          <div className="assistant-conversation-column">
          {fullPage?<div className="assistant-scope-bar"><label>Portfolio <strong>{context.portfolio_name??"None selected"}</strong></label><label>Company <select aria-label="Assistant company context" value={assistantCompany?.id??""} onChange={event=>setAssistantCompany(companyChoices.find(row=>row.id===event.target.value)??null)}><option value="">All companies</option>{companyChoices.map(row=><option key={row.id} value={row.id}>{row.symbol} · {row.name}</option>)}</select></label></div>:null}
          <header className="assistant-header">
            <div>
              <strong>Assistant</strong>
            </div>
            <div className="flex gap-2">
              {!fullPage?<><button
                className="icon-btn assistant-history-button"
                aria-expanded={showChats}
                aria-label="Saved chats"
                onClick={() => setShowChats(!showChats)}
              >
                Previous chats ⌄
              </button>
              <button
                className="icon-btn"
                aria-label={
                  expanded ? "Collapse Assistant" : "Expand Assistant"
                }
                onClick={() => setExpanded(!expanded)}
              >
                {expanded ? "↙" : "↗"}
              </button>
              <button
                className="icon-btn"
                aria-label="Close Assistant"
                onClick={() => {
                  setOpened(false);
                  trigger.current?.focus();
                }}
              >
                ×
              </button></>:<Link href="/dashboard">Back to workspace ↗</Link>}
            </div>
          </header>
          {showChats && !fullPage ? (
            <nav
              className="assistant-chat-list assistant-chat-dropdown"
              aria-label="Saved conversations"
            >
              <button
                className="btn btn-secondary"
                onClick={() => void newChat()}
              >
                New chat
              </button>
              {chats.map((chat) => (
                <button
                  key={chat.id}
                  aria-current={selected === chat.id ? "true" : undefined}
                  onClick={() => {
                    setSelected(chat.id);
                    setShowChats(false);
                    nearBottom.current = true;
                  }}
                >
                  {chat.title}
                  {chat.active_run ? <small> · Generating</small> : null}
                </button>
              ))}
              {chatCursor ? (
                <button onClick={() => void refreshChats(chatCursor)}>
                  More chats
                </button>
              ) : null}
            </nav>
          ) : null}
          {!fullPage?<div className="assistant-toolbar">
            <span>
              {chats.find((c) => c.id === selected)?.title ?? "New chat"}
            </span>
            <button onClick={() => void newChat()}>New chat</button>
          </div>:null}
          <div
            className="assistant-messages"
            ref={scroller}
            onScroll={() => {
              const e = scroller.current;
              if (e)
                nearBottom.current =
                  e.scrollHeight - e.scrollTop - e.clientHeight < 90;
              if (nearBottom.current) setNewMessages(false);
            }}
          >
            {history?.next_cursor ? (
              <button
                className="btn btn-secondary"
                onClick={() =>
                  selected && void loadHistory(selected, history.next_cursor!)
                }
              >
                Earlier messages
              </button>
            ) : null}
            {!history?.items.length && !live.length ? (
              <div className="assistant-empty">
                <h2>What would you like to understand?</h2>
                <p>
                  Ask about a company, compare evidence, or discuss your
                  portfolio. Sources and missing data stay visible.
                </p>
                <div className="assistant-suggestions">{suggestions.map((text) => <button key={text} type="button" onClick={() => prefill(text)}>{text}</button>)}</div>
              </div>
            ) : null}
            {history?.items.map((message) => (
              <ChatMessageView key={message.id} message={message} />
            ))}
            {conversationTokens.answers ? (
              <p className="assistant-tokens assistant-tokens-total" data-testid="conversation-tokens">
                Conversation so far: Input {conversationTokens.input.toLocaleString("en-US")} · Output{" "}
                {conversationTokens.output.toLocaleString("en-US")} · {conversationTokens.calls} model calls
                {conversationTokens.unreported ? ` · ${conversationTokens.unreported} answer(s) not fully reported` : ""}
              </p>
            ) : null}
            {live
              .filter(
                (r) =>
                  !history?.items.some(
                    (m) =>
                      m.execution_id === r.execution_id &&
                      m.role === "assistant",
                  ),
              )
              .map((run) => (
                <article
                  key={run.execution_id}
                  className="assistant-message assistant-answer"
                >
                  <div className="assistant-message-label">
                    <span className="assistant-avatar" aria-hidden="true">R</span>
                    <small className="assistant-status">Unverified draft</small>
                  </div>
                  {run.text ? <Markdown text={run.text} /> : null}
                  <p role="status" className="assistant-status">
                    {active(run.status)
                      ? run.activity
                      : outcomeLabel(run.status, run.error_code)}
                  </p>
                  {run.warning ? (
                    <p className="assistant-warning">{run.warning}</p>
                  ) : null}
                </article>
              ))}
          </div>
          {newMessages ? (
            <button
              className="assistant-new-messages"
              onClick={() => {
                nearBottom.current = true;
                if (scroller.current)
                  scroller.current.scrollTop = scroller.current.scrollHeight;
                setNewMessages(false);
              }}
            >
              New messages ↓
            </button>
          ) : null}
          {history?.summary_failure ? (
            <div className="assistant-warning">
              Older discussion wasn’t summarized.{" "}
              <button
                onClick={() =>
                  selected &&
                  void retrySummary(selected).then(() => loadHistory(selected))
                }
              >
                Retry summary
              </button>
            </div>
          ) : null}
          {history?.summary ? (
            <div className="assistant-summary-actions">
              <button
                onClick={() =>
                  void navigator.clipboard
                    .writeText(history.summary!.text)
                    .catch(() => setError("Could not copy summary"))
                }
              >
                Copy summary
              </button>
              <button
                onClick={() =>
                  selected &&
                  void continueChat(selected)
                    .then((chat) => {
                      setSelected(chat.id);
                      void refreshChats();
                    })
                    .catch((e) => setError(e.message))
                }
              >
                Continue in new chat
              </button>
            </div>
          ) : null}
          {error ? (
            <p className="assistant-warning" role="alert">
              {error}
            </p>
          ) : null}
          {history?.items.length && !running ? <div className="assistant-suggestions assistant-followups">{suggestions.map((text) => <button key={text} type="button" onClick={() => prefill(text)}>{text}</button>)}</div> : null}
          <form
            className="assistant-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send();
            }}
          >
            <textarea
              ref={composer}
              aria-label="Message Assistant"
              maxLength={8000}
              placeholder={history?.items.length ? "Ask a follow-up…" : "Ask a question…"}
              value={draft}
              onChange={(e) =>
                setDrafts((old) => ({
                  ...old,
                  [selected ?? "new"]: e.target.value,
                }))
              }
              onKeyDown={(e) => {
                if (
                  e.key === "Enter" &&
                  !e.shiftKey &&
                  !e.nativeEvent.isComposing
                ) {
                  e.preventDefault();
                  void send();
                }
              }}
            />
            <div className="assistant-composer-footer">
              <span className="assistant-chip" title="Context for the next message">
                {context.symbol ?? "All companies"} · {context.portfolio_name ?? "No default portfolio"}
                {!contextReady ? " · Loading…" : ""}
              </span>
              <div className="assistant-composer-actions">
                <AssistantProviderSwitch key={account} onProviderChange={setProvider} onSavingChange={setProviderSaving} />
                {running ? (
                  <button
                    type="button"
                    className="assistant-send assistant-stop"
                    aria-label="Stop generating"
                    title="Stop generating"
                    onClick={() =>
                      void stopRun(running.execution_id).catch((e) =>
                        setError(e.message),
                      )
                    }
                  >
                    ■
                  </button>
                ) : (
                  <button
                    className="assistant-send"
                    aria-label="Send"
                    title="Send (Enter)"
                    disabled={!draft.trim() || submitting || providerSaving || !contextReady}
                  >
                    {submitting ? "…" : "↑"}
                  </button>
                )}
              </div>
            </div>
          </form>
          </div>
          {fullPage?<AssistantEvidenceContext context={context} sources={history?.items.slice().reverse().find(message=>message.role==="assistant")?.evidence?.sources??[]}/>:null}
        </section>
      ) : null}
    </Workspace.Provider>
  );
}
