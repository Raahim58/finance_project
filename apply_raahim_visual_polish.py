#!/usr/bin/env python3
"""Conservative visual-style correction for Raahim ui-updates.

Run from the repository root:
  python3 apply_raahim_visual_polish.py --check
  python3 apply_raahim_visual_polish.py --apply

No structural, business logic, API, or routing files are changed.
"""
from __future__ import annotations

import argparse
import difflib
import pathlib
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true', help='Write the proposed changes. Without this flag the script previews diffs.')
parser.add_argument('--check', action='store_true', help='Verify that the current files support the patch, without writing.')
args = parser.parse_args()
root = pathlib.Path.cwd()
if not (root / 'apps/web/app/layout.tsx').is_file():
    sys.exit('Run this from the finance_project repository root.')

files: dict[str, list[str]] = {}

def replace(path: str, old: str, new: str):
    files.setdefault(path, [])
    files[path].append(('replace', old, new))

def append(path: str, marker: str, css: str):
    files.setdefault(path, [])
    files[path].append(('append', marker, css))

G = 'apps/web/app/globals.css'
W = 'apps/web/app/workspace-system.css'

# Restore reference palette: pure paper white and cooler, quieter greys.
replace(G, '  --canvas: #fafbfc;', '  --canvas: #ffffff;')
replace(G, '  --surface: #f3f4f6;', '  --surface: #f1f2f4;')
replace(G, '  --line: #e5e8ec;', '  --line: #e7e9ed;')
replace(G, '  --muted: #70757d;', '  --muted: #666d78;')
replace(G,
 '.workstation-shell .app-sidebar .nav-item[aria-current="page"] .rail-icon { background:none; }',
 '.workstation-shell .app-sidebar .nav-item[aria-current="page"] .rail-icon { background:var(--surface); }')
replace(G,
 '''/* No painted selection indicators in any sidebar, context panel, or table row. */
.workstation-shell aside [aria-current],.workstation-shell aside [aria-selected],.workstation-shell aside [aria-pressed],.workstation-shell aside [data-active],.workstation-shell [data-portfolio-panel="context"] [aria-current],.workstation-shell [data-portfolio-panel="context"] [aria-selected],.workstation-shell main tr[aria-selected] { background-color:transparent!important; box-shadow:none!important; border-left-color:transparent!important; }
.workstation-shell aside button[aria-current],.workstation-shell aside a[aria-current],.workstation-shell aside button[aria-selected],.workstation-shell aside button[aria-pressed],.workstation-shell [data-portfolio-panel="context"] button[aria-current] { color:inherit!important; }
.workstation-shell aside [aria-current]::before,.workstation-shell aside [aria-selected]::before,.workstation-shell aside [aria-pressed]::before,.workstation-shell aside [aria-current]::after,.workstation-shell aside [aria-selected]::after,.workstation-shell aside [aria-pressed]::after,.workstation-shell main tr[aria-selected]::before,.workstation-shell main tr[aria-selected]::after { display:none!important; }
.workstation-shell main tr[aria-selected] td:first-child,.workstation-shell aside nav [aria-current],.workstation-shell aside nav [aria-selected],.workstation-shell aside nav [aria-pressed] { box-shadow:none!important; background-color:transparent!important; }
.workstation-shell aside [aria-current="page"],.workstation-shell aside [aria-current="true"],.workstation-shell aside [aria-selected="true"],.workstation-shell aside [aria-pressed="true"] { font-weight:600; }
.workstation-shell .app-sidebar .nav-item[aria-current="page"] .rail-icon { background:none!important; }
''',
 '''/* A single, visible selection grammar: soft grey navigation and table selection. */
.workstation-shell aside :is(a,button)[aria-current="page"],
.workstation-shell aside :is(a,button)[aria-selected="true"],
.workstation-shell aside :is(a,button)[aria-pressed="true"] {
  background-color:var(--surface);
  color:var(--ink);
  border-radius:7px;
  font-weight:600;
}
.workstation-shell main tr[aria-selected="true"] { background-color:#f4f5f7; }
.workstation-shell main tr[aria-selected="true"] td:first-child { box-shadow:none; }
''')
replace(G,
 '''/* Selected tabs are bold only (no underline, box or colour); tab bars sit in the middle. */
.ptabs a[aria-current="page"]::after { display:none; }''',
 '''/* Keep the current navigation structure, but restore a crisp active underline. */
.ptabs a[aria-current="page"]::after { display:block; }''')
replace(G,
 '''.ptabs a[aria-current="page"],.workspace-header-tabs [aria-current="page"],.workspace-header-tabs [aria-selected="true"] { font-weight:650; color:var(--ink); border-bottom-color:transparent; }
.workstation-shell [role="tablist"] [aria-selected="true"],.workstation-shell [class*="ubtabs"] [aria-selected="true"],.workstation-shell [class*="atementTabs"] [aria-current="page"],.workstation-shell [class*="tabs"] [aria-selected="true"],.workstation-shell [class*="tabs"] [aria-current="page"] { border-bottom-color:transparent!important; box-shadow:none!important; font-weight:650!important; color:var(--ink); }
.workstation-shell [role="tablist"],.workstation-shell [class*="ubtabs"],.workstation-shell [class*="atementTabs"] { justify-content:center; }
.workstation-shell [class*="ubtabs"] { margin-bottom:30px!important; }''',
 '''.ptabs a[aria-current="page"],.workspace-header-tabs [aria-current="page"],.workspace-header-tabs [aria-selected="true"] { font-weight:600; color:var(--ink); border-bottom-color:var(--ink); }
.workstation-shell [role="tablist"] [aria-selected="true"],.workstation-shell [class*="ubtabs"] [aria-selected="true"],.workstation-shell [class*="atementTabs"] [aria-current="page"],.workstation-shell [class*="tabs"] [aria-selected="true"],.workstation-shell [class*="tabs"] [aria-current="page"] { border-bottom-color:var(--ink)!important; box-shadow:none!important; font-weight:600!important; color:var(--ink); }
/* Page-local tablists retain their own alignment and rhythm. */''')

# Remove destructive cross-screen type overrides. Local CSS modules already define headings.
replace(W,
 '''  font-weight:600;
  letter-spacing:-.025em;
  line-height:1.35;
}
.workstation-shell main h1 { font-size:24px!important; }
.workstation-shell main h2 { font-size:18px!important; }
.workstation-shell main :is(h3,h4) { font-size:15px!important; }
.workstation-shell :is(main,.assistant-drawer) :is(table,dl) { font-variant-numeric:tabular-nums; }
.workstation-shell main :is(th) { font-size:12px; font-weight:500; }
.workstation-shell main :is(td) { font-size:13px; }''',
 '''  font-weight:600;
  letter-spacing:-.025em;
  line-height:1.3;
}
/* Deliberately no global heading-size or table-cell overrides: page modules own the scale. */
.workstation-shell :is(main,.assistant-drawer) :is(table,dl) { font-variant-numeric:tabular-nums; }''')
replace(W, '  border-bottom-color:transparent;\n}\n.ptabs a[aria-current="page"]::after { display:none; }',
        '  border-bottom-color:var(--ink);\n}\n.ptabs a[aria-current="page"]::after { display:block; }')

# Improve the AI brief *at the component source*, rather than re-theme through global attributes.
B = 'apps/web/components/ai-brief.module.css'
brief_old = '''.card { border:1px solid #e4ddcf; border-radius:7px; background:#f3eee3; padding:14px 16px; margin-bottom:16px; }
.card header { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:8px; }
.card h2 { margin:0; }
.card small { color:var(--muted); }
.headline { font-weight:600; margin:0 0 6px; }
.card p { margin:0 0 8px; line-height:1.55; }
.card ul { margin:0 0 8px; padding-left:18px; display:grid; gap:5px; }
.refs abbr { color:var(--muted); text-decoration:none; margin-left:4px; cursor:help; font-size:11px; }
.watch,.note { color:var(--muted); }
.note button { margin-left:10px; border:1px solid #e4ddcf; border-radius:6px; padding:3px 9px; cursor:pointer; }
'''
brief_new = '''/* Evidence briefs read as editorial analysis, not a contrasting yellow card. */
.card { border:0; border-top:1px solid var(--line); border-radius:0; background:transparent; padding:20px 0 18px; margin:12px 0 20px; color:var(--ink); font-family:var(--font-ui); }
.card header { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:6px 16px; margin-bottom:13px; }
.card h2 { margin:0; font-size:18px; line-height:1.3; font-weight:600; letter-spacing:-.025em; }
.card small { color:var(--muted); font-size:11px; line-height:1.5; font-weight:400; }
.headline { font-size:17px; line-height:1.42; font-weight:600; letter-spacing:-.018em; margin:0 0 10px; color:var(--ink); }
.card p { margin:0 0 12px; font-size:13.5px; line-height:1.65; color:var(--ink-2); overflow-wrap:break-word; }
.card ul { margin:0 0 13px; padding-left:20px; display:grid; gap:9px; color:var(--ink-2); font-size:13.5px; line-height:1.6; }
.card li { padding-left:2px; overflow-wrap:break-word; }
.refs abbr { display:inline; color:var(--muted); text-decoration:none; margin-left:4px; cursor:help; font-size:10.5px; white-space:nowrap; }
.card .watch { border-top:1px solid var(--line); padding-top:12px; margin-top:15px; color:var(--ink-2); }
.card .watch b { color:var(--ink); font-weight:600; }
.card .note { color:var(--muted); font-size:12px; }
.note button { margin-left:10px; border:1px solid var(--line); background:var(--paper); border-radius:7px; padding:5px 10px; color:var(--ink); font-size:12px; cursor:pointer; }
.note button:hover { background:var(--surface); }
'''
replace(B, brief_old, brief_new)

# Purposeful, scoped corrections in the owning CSS module. No positioning or grid rewrites.
append('apps/web/components/markets/markets.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: consistent legibility without changing market layout. */
.page { font-size:14px; line-height:1.5; }
.catalogTabs,.catalogList a,.catalogViews button { font-size:13.5px; }
.catalogList h2,.catalogSubheading { font-size:15px; font-weight:600; }
.main :is(p,li),.rail :is(p,li) { line-height:1.6; }
.table table { font-size:13px; }
.table th { font-size:12px; color:var(--muted); font-weight:500; }
.table td { font-size:13px; line-height:1.5; }
.detailFacts,.detailFacts dd,.detailFacts dt { font-size:13px; }
.detailDeeper>a,.detailDeeper>button,.sectorCompanies button { font-size:13px; }
.followUp { font-size:13px!important; line-height:1.55; }
.askComposer textarea,.detailComposer textarea { font-size:13px; }
.digestBody p { font-size:14px; line-height:1.62; }
.digestBody h2 { font-size:19px; }
''')
append('apps/web/components/company/company.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: financial detail remains readable across panes. */
.workspace { font-size:14px; line-height:1.55; }
.companyNav button { font-size:13.5px; }
.tabs button,.statementTabs button { font-size:13px; }
.keyFacts > div { font-size:13px; }
.keyFacts strong { font-size:12px; }
.table { font-size:13px; }
.table th { font-size:12px; font-weight:500; color:var(--muted); }
.table td,.table td button { font-size:13px; }
.table td small,.caption { font-size:11px; }
.filters label,.filters select { font-size:12.5px; }
.rightBody h2 { font-size:18px; }
.holdingStats span { font-size:11px; }
.holdingStats strong { font-size:14px; }
.askAbout button { font-size:13.5px!important; }
.composer textarea { font-size:13px; }
''')
append('apps/web/components/research-workspace/workspace.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: restore research page hierarchy and table readability. */
.heading { font-size:30px!important; font-weight:650; letter-spacing:-.035em; line-height:1.2; }
.sub { font-size:13.5px; line-height:1.6; }
.title,.rightHeader h2 { font-size:18px; font-weight:600; }
.nav button,.nav a { font-size:13.5px; }
.field,.detail,.actions button,.actions a,.button { font-size:13px; }
.table,.table td,.table td button { font-size:13px; }
.table th { font-size:12px; font-weight:500; color:var(--muted); }
.table td { padding:13px 9px; }
.table td small,.documentList small { font-size:11px; }
.tabs button,.questions button { font-size:13.5px; }
''')
append('apps/web/components/portfolio/build/build.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: share readable table/rail typography with the other workspaces. */
.root { font-size:14px; line-height:1.5; }
.control,.field,.sub { font-size:13px; }
.table,.table td,.table .num,.weightInput,.metrics { font-size:13px; }
.table th,.metrics th { font-size:12px; color:var(--muted); font-weight:500; }
.allocationHeading h2,.h2 { font-size:18px; font-weight:600; }
.insight,.insight p,.constraints,.details { font-size:13.5px; line-height:1.6; }
.legend,.allocationHeading>span { font-size:11.5px; }
.ask textarea { font-size:13px; }
''')
append('apps/web/components/portfolio/ips/ips.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: consistent form, metadata and focus appearance. */
.layout :is(a,button,input,select):focus-visible { outline:2px solid var(--focus); outline-offset:3px; }
.nav a,.nav button { font-size:13.5px; }
.subtitle,.rail p { font-size:13.5px; }
.tableWrap table,.binding { font-size:13px; }
''')
append('apps/web/components/portfolio/quant/quant.module.css', 'RAAHIM type-rhythm v1', '''
/* RAAHIM type-rhythm v1: keep charts prominent and explanations readable. */
.caption,.description,.portfolioFacts { font-size:13.5px; line-height:1.6; }
.railTitle { font-size:18px; font-weight:600; }
.row,.row dt,.row dd { font-size:13px; line-height:1.5; }
.assumptions,.compare label { font-size:13px; }
.compareNote,.readonly { font-size:12px; line-height:1.6; }
.kpi dt,.stats,.legend { font-size:12px; }
''')

# Normalize LLM-produced Markdown, but do not affect chart/tool layouts or message content.
append(G, 'RAAHIM brief typography v1', '''
/* RAAHIM brief typography v1: the assistant shares the same editorial text scale. */
.workstation-shell .app-sidebar .nav-item { font-size:12px; line-height:1.3; }
.workstation-shell .app-sidebar .nav-item[aria-current="page"] { background-color:var(--surface); color:var(--ink); }
.assistant-markdown { color:var(--ink-2); font-size:14px; line-height:1.7; overflow-wrap:anywhere; }
.assistant-markdown p { margin:0 0 12px; }
.assistant-markdown :is(h1,h2,h3) { color:var(--ink); font-weight:600; letter-spacing:-.02em; line-height:1.35; }
.assistant-markdown h1 { font-size:19px; margin:20px 0 9px; }
.assistant-markdown h2 { font-size:17px; margin:18px 0 8px; }
.assistant-markdown h3 { font-size:15px; margin:16px 0 7px; }
.assistant-markdown :is(ul,ol) { padding-left:20px; margin:8px 0 14px; }
.assistant-markdown li { margin:6px 0; }
.assistant-markdown :is(strong,b) { color:var(--ink); font-weight:600; }
.assistant-markdown :is(table) { width:100%; border-collapse:collapse; font-size:12.5px; }
.assistant-markdown :is(th,td) { padding:9px 10px; border-bottom:1px solid var(--line); text-align:left; }
.assistant-markdown th { color:var(--muted); font-weight:500; }
''')

originals = {}
changes = {}
for path, steps in files.items():
    p = root / path
    if not p.exists():
        sys.exit(f'Cannot find {path}; no changes written.')
    original = p.read_text(encoding='utf-8')
    value = original
    for method, old, new in steps:
        if method == 'replace':
            count = value.count(old)
            if count != 1:
                sys.exit(f'Expected exactly 1 match, found {count} in {path}, for {old[:100]!r}. No changes written.')
            value = value.replace(old, new, 1)
        else:
            if old in value:
                sys.exit(f'Patch already present in {path}. No changes written.')
            value = value.rstrip() + '\n' + new.rstrip() + '\n'
    originals[path] = original
    changes[path] = value

print(f'Validated {len(files)} files against branch styling expectations.')
if args.check:
    print('All transformations available; no files changed.')
    sys.exit(0)
if args.apply:
    for path, value in changes.items():
        (root / path).write_text(value, encoding='utf-8')
    print('Updated CSS only:')
    for p in files: print('  '+p)
    print('Review with git diff --check && git diff --stat; run npm test/build in apps/web.')
else:
    print('PREVIEW ONLY. Run with --apply to write these changes.\n')
    for path in files:
        before = originals[path].splitlines(keepends=True)
        after = changes[path].splitlines(keepends=True)
        delta = list(difflib.unified_diff(before, after, fromfile='a/'+path, tofile='b/'+path, n=2))
        print(''.join(delta[:65]))
