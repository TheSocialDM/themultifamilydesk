"""Internal weekly Market Desk report.

  python3 _desk/weekly.py log /tmp/desk/brief.json   # after every refresh
  python3 _desk/weekly.py report                      # rebuild the 7 day report

Keeps a 7 day rolling log in _desk/week_log.json and writes
_desk/reports/latest.json and latest.md. Lists headlines and counts only.
It never writes commentary or opinions in anyone's name.
"""
import datetime as dt, json, os, re, sys
from urllib.parse import urlsplit, urlunsplit

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "week_log.json")
REP = os.path.join(HERE, "reports")
KEEP_DAYS = 8


def canon(u):
    p = urlsplit(u.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""), p.path.rstrip("/"), "", ""))


def now():
    return dt.datetime.now(dt.timezone.utc)


def load():
    if os.path.exists(LOG):
        try:
            return json.load(open(LOG))
        except Exception:
            pass
    return {"runs": [], "stories": {}}


def save(log):
    cut = (now() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    log["runs"] = [r for r in log["runs"] if r["time"] >= cut]
    log["stories"] = {k: v for k, v in log["stories"].items() if v["last"] >= cut}
    json.dump(log, open(LOG, "w"), indent=0, ensure_ascii=False)


def cmd_log(brief_path):
    b = json.load(open(brief_path))
    log = load()
    t = b.get("updated") or now().isoformat()
    fates = {}
    for x in b.get("seen", []):
        fates[x["fate"]] = fates.get(x["fate"], 0) + 1
    pub = {canon(p["link"]): p for p in b.get("published", [])}
    log["runs"].append({"time": t, "collected": b.get("collected", 0), "published": len(pub), "fates": fates,
                        "health": {h["name"]: h["state"] for h in b.get("health", []) if h["public"]}})
    for x in b.get("seen", []):
        if not x.get("link"):
            continue
        k = canon(x["link"])
        s = log["stories"].setdefault(k, {"title": x["title"], "source": x["source"], "first": t, "last": t, "fate": x["fate"]})
        s["last"] = t
        if k in pub:
            p = pub[k]
            s.update(fate="published", filters=p.get("filters", []), geo=p.get("geo", []), topics=p.get("topics", []), date=p.get("date"), link=p["link"])
        elif s["fate"] != "published":
            s["fate"] = x["fate"]
    save(log)
    cmd_report()


PRIORITY = [("Arizona", "Phoenix and Arizona"), ("Seattle", "Seattle and Washington"), ("Rents", "Rents and renewals"),
            ("Operations", "Occupancy and concessions"), ("Capital Markets", "Lending and debt"), ("Rates", "Rates"),
            ("Policy", "Policy and regulation"), ("Supply", "New supply"), ("Insurance", "Insurance"), ("Property taxes", "Property taxes")]


def cmd_report():
    log = load()
    end = now(); start = end - dt.timedelta(days=7)
    runs = [r for r in log["runs"] if r["time"] >= start.isoformat()]
    stories = [s for s in log["stories"].values() if s["last"] >= start.isoformat()]
    published = [s for s in stories if s["fate"] == "published"]
    by_fate = {}
    for s in stories:
        by_fate[s["fate"]] = by_fate.get(s["fate"], 0) + 1
    # sources that were not healthy in any run
    issues = {}
    for r in runs:
        for name, state in r["health"].items():
            if state != "healthy":
                issues.setdefault(name, {}).setdefault(state, 0)
                issues[name][state] += 1
    topics = {}
    for s in published:
        for f in set(s.get("topics", []) + s.get("geo", [])):
            topics[f] = topics.get(f, 0) + 1
    picks, used = [], set()
    for key, label in PRIORITY:
        cands = [s for s in published if key in s.get("geo", []) + s.get("topics", []) and s["link"] not in used]
        cands.sort(key=lambda s: s.get("date") or "", reverse=True)
        for s in cands[:2]:
            picks.append({"why": label, "title": s["title"], "source": s["source"], "date": s.get("date"), "link": s["link"]})
            used.add(s["link"])
        if len(picks) >= 6:
            break
    gaps = [label for key, label in PRIORITY[:2] if not any(key in s.get("geo", []) for s in published)]
    rep = {"from": start.isoformat(timespec="minutes"), "to": end.isoformat(timespec="minutes"), "refreshes": len(runs),
           "collected": len(stories), "published": len(published), "filtered_out": {k: v for k, v in by_fate.items() if k != "published"},
           "source_issues": issues, "topics": dict(sorted(topics.items(), key=lambda kv: -kv[1])), "for_melanie": picks, "coverage_gaps": gaps}
    os.makedirs(REP, exist_ok=True)
    json.dump(rep, open(os.path.join(REP, "latest.json"), "w"), indent=1, ensure_ascii=False)
    reasons = {"off_topic": "off topic for apartment owners", "too_old": "too old", "duplicate": "duplicate", "opinion": "opinion or column",
               "no_link": "no link", "kept": "relevant but below the top 30 or internal only"}
    md = [f"# Market Desk weekly, internal", f"{start:%b %-d} to {end:%b %-d, %Y} · {len(runs)} refreshes", "",
          f"**Collected:** {len(stories)} unique stories  ", f"**Passed and published:** {len(published)}  "]
    for k, v in sorted(rep["filtered_out"].items(), key=lambda kv: -kv[1]):
        md.append(f"- Filtered: {v} {reasons.get(k, k)}")
    md += ["", "**Source problems:**" if issues else "**Source problems:** none"]
    for name, st in issues.items():
        md.append(f"- {name}: " + ", ".join(f"{k} in {v} of {len(runs)} refreshes" for k, v in st.items()))
    md += ["", "**Topics this week:** " + ", ".join(f"{k} {v}" for k, v in list(rep["topics"].items())[:8]), "",
           "**Worth Melanie's attention** (headlines only, no commentary):"]
    for p in picks:
        md.append(f"- [{p['why']}] {p['title']} ({p['source']}, {p['date']}) {p['link']}")
    if gaps:
        md += ["", "**Coverage gaps:** no published stories this week for " + " or ".join(gaps) + "."]
    open(os.path.join(REP, "latest.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "log":
        cmd_log(sys.argv[2])
    else:
        cmd_report()
