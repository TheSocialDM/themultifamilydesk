import json, html, sys, datetime as dt
r = json.load(open(sys.argv[1])); out = sys.argv[2]
E = html.escape
f = lambda s: dt.datetime.fromisoformat(s).astimezone(dt.timezone(dt.timedelta(hours=-7)))
reasons = {"off_topic": "Off topic for apartment owners", "too_old": "Too old", "duplicate": "Duplicates", "opinion": "Opinion or columns", "no_link": "No link", "kept": "Relevant, outside the top 30"}
filt = "".join(f"<tr><td>{E(reasons.get(k,k))}</td><td>{v}</td></tr>" for k, v in sorted(r["filtered_out"].items(), key=lambda kv: -kv[1]))
iss = "".join(f"<li><b>{E(n)}</b>: " + ", ".join(f"{E(k)} in {v} of {r['refreshes']} refreshes" for k, v in st.items()) + "</li>" for n, st in r["source_issues"].items()) or "<li>None. Every public source answered.</li>"
top = "".join(f'<span class="chip">{E(k)} <b>{v}</b></span>' for k, v in list(r["topics"].items())[:10])
picks = "".join(f'<li><div class="why">{E(p["why"])}</div><a href="{E(p["link"])}" target="_blank" rel="noopener">{E(p["title"])}</a><div class="src">{E(p["source"])} · {E(p["date"] or "")}</div></li>' for p in r["for_melanie"])
gaps = f'<p class="gap">No published stories this week for {E(" or ".join(r["coverage_gaps"]))}.</p>' if r["coverage_gaps"] else ""
a, b = f(r["from"]), f(r["to"])
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Market Desk weekly (internal)</title>
<style>body{{margin:0;font:16px/1.55 -apple-system,system-ui,sans-serif;color:#101317;background:#fff}}.w{{max-width:760px;margin:0 auto;padding:28px 20px 60px}}h1{{font:400 34px/1.1 Georgia,serif;margin:6px 0}}.k{{font-size:13px;color:#8a2433;letter-spacing:.04em;text-transform:uppercase}}.sub{{color:#5b626b;margin:0 0 24px}}
.n{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 28px}}.n div{{border-top:2px solid #101317;padding-top:10px}}.n b{{display:block;font:400 36px Georgia,serif}}.n span{{font-size:13px;color:#5b626b}}
h2{{font-size:15px;margin:28px 0 10px;border-top:1px solid #e3e5e8;padding-top:18px}}table{{width:100%;border-collapse:collapse}}td{{padding:6px 0;border-bottom:1px solid #f0f1f2}}td+td{{text-align:right}}ul{{padding:0;list-style:none;margin:0}}li{{margin:0 0 14px}}
.chip{{display:inline-block;border:1px solid #e3e5e8;border-radius:999px;padding:4px 10px;margin:0 6px 8px 0;font-size:14px}}.why{{font-size:12px;color:#8a2433;text-transform:uppercase;letter-spacing:.04em}}a{{color:#101317;font:400 19px/1.3 Georgia,serif;text-decoration:none;border-bottom:1px solid #c9cdd2}}.src{{font-size:13px;color:#5b626b;margin-top:2px}}.gap{{background:#f7f7f8;padding:12px 14px;border-radius:6px}}.ft{{margin-top:32px;font-size:13px;color:#5b626b}}</style></head>
<body><div class="w"><div class="k">Internal · not public</div><h1>Market Desk weekly</h1><p class="sub">{a:%b %-d} to {b:%b %-d, %Y} · {r['refreshes']} refreshes</p>
<div class="n"><div><b>{r['collected']}</b><span>stories collected</span></div><div><b>{r['published']}</b><span>passed and published</span></div><div><b>{r['collected']-r['published']}</b><span>filtered out</span></div></div>
<h2>Why stories were filtered</h2><table>{filt}</table><h2>Source problems</h2><ul>{iss}</ul><h2>Topics on the desk</h2><div>{top}</div>
<h2>Worth Melanie's attention</h2><p class="sub" style="margin:0 0 12px">Headlines only. Nothing here is written in her name.</p><ul>{picks}</ul>{gaps}
<p class="ft">Built automatically from the Market Desk refresh log. Updated {b:%b %-d, %-I:%M %p} Arizona time.</p></div></body></html>"""
open(out, "w").write(page)
