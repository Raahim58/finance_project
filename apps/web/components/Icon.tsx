export type IconName = "grid"|"briefcase"|"market"|"search"|"assistant"|"bell"|"lightbulb"|"activity"|"settings"|"plus"|"more"|"chevron"|"arrowUp"|"arrowDown"|"expand"|"close"|"menu"|"company"|"document"|"warning"|"check"|"clock"|"drag";

const paths: Record<IconName, React.ReactNode> = {
  grid:<><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></>,
  briefcase:<><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><rect x="3" y="7" width="18" height="13" rx="1"/><path d="M3 12h18M10 12v2h4v-2"/></>,
  market:<><path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/><path d="m3 7 6-4 6 6 6-5"/></>,
  search:<><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
  assistant:<><path d="M5 5h14v11H9l-4 4V5Z"/><path d="M9 9h6M9 12h4"/></>,
  bell:<><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></>,
  lightbulb:<><path d="M9 18h6M10 22h4M8 14a7 7 0 1 1 8 0c-1 1-1 2-1 3H9c0-1 0-2-1-3Z"/></>,
  activity:<><path d="M3 12h4l2-6 4 12 2-6h6"/></>,
  settings:<><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
  plus:<path d="M12 5v14M5 12h14"/>, more:<><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>, chevron:<path d="m9 18 6-6-6-6"/>,
  arrowUp:<path d="m18 15-6-6-6 6"/>, arrowDown:<path d="m6 9 6 6 6-6"/>, expand:<><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></>, close:<path d="M6 6l12 12M18 6 6 18"/>, menu:<path d="M4 7h16M4 12h16M4 17h16"/>,
  company:<><path d="M4 21V5l8-3v19M12 8h8v13M7 7h2M7 11h2M7 15h2M15 12h2M15 16h2M2 21h20"/></>,
  document:<><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5M9 12h6M9 16h6"/></>, warning:<><path d="M12 3 2 21h20L12 3Z"/><path d="M12 9v5M12 18h.01"/></>, check:<path d="m5 12 4 4L19 6"/>, clock:<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>, drag:<path d="M8 6h.01M8 12h.01M8 18h.01M16 6h.01M16 12h.01M16 18h.01"/>
};

export function Icon({name,size=17,className=""}:{name:IconName;size?:number;className?:string}) {
  return <svg aria-hidden="true" className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
