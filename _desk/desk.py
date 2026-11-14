#!/usr/bin/env python3
"""The Market Desk fetcher.

Reads public RSS feeds listed in sources.json, scores each item for relevance
to multifamily owners and operators, removes duplicates and noise, checks feed
health, and writes two files:

  out/desk.json   public feed: only sources marked public, headline, source,
                  date, link, access label, topic tags, optional approved note
  out/brief.json  internal: every source (WSJ included), feed health, and the
                  ranked shortlist for the weekly desk brief

Rules this script enforces:
  * RSS only. Article pages are never requested, so paywalls and article
    bodies are never touched.
  * Publisher headline, link and attribution are kept exactly as published.
  * No text is written in Melanie's name. A note appears publicly only if an
    editor has approved it in notes.json.
  * Polite fetching: identifying user agent, conditional GET (ETag and
    Last-Modified), a minimum interval per source, and any crawl delay.

Usage:
  python3 desk.py --live                 fetch the feeds (scheduled job)
  python3 desk.py --snapshot FILE        run on a saved capture (testing)
"""
import argparse, datetime as dt, email.utils, hashlib, html, json, os, re, sys, time
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("DESK_OUT", os.path.join(HERE, "out"))
MAX_AGE_DAYS = 14
SHOW_DRAFTS = os.environ.get("DESK_SHOW_DRAFTS") == "1"  # private sample only

# ---------------------------------------------------------------- taxonomy
# (pattern, points, topic). Patterns are matched against the headline plus the
# feed's own description. Points reflect relevance to an apartment operator.
TOPICS = [
    (r"\bmultifamily|apartment|rental market|renters?\b|\brents?\b|\bunits?\b|lease-?up|build-to-rent|\bBTR\b", 4, "Multifamily"),
    (r"rent growth|rents? (rose|fell|rise|fall|increase|decline)|rent prices|asking rents?|renewal", 3, "Rents"),
    (r"\bREITs?\b|BREIT|funds? from operations|\bFFO\b", 3, "REITs"),
    (r"(?<!market-)\brate(s)?\b|treasur|yield|\bfed\b|federal reserve|inflation|\bCPI\b|\bPPI\b|SOFR|mortgage rate", 2, "Rates"),
    (r"refinanc|\bloans?\b|lend|debt|\bCLO\b|CMBS|delinquen|maturit|freddie|fannie|bridge loan|financing|capital markets|impairment|default", 3, "Capital Markets"),
    (r"insurance|insurer", 2, "Insurance"),
    (r"property tax|tax assessment", 3, "Property taxes"),
    (r"concession|occupanc|vacanc|absorption", 3, "Operations"),
    (r"supply|completion|construction|groundbreak|develop|permitting|starts\b", 2, "Supply"),
    (r"data cent(er|re)s?|semiconductor|chip fab|factory|plant\b", 1, "Employment"),
    (r"\bjobs?\b|employment|unemployment|jobless|payroll|hiring", 2, "Employment"),
    (r"migration|relocat|population", 2, "Migration"),
    (r"home sales|homeownership|home prices|housing|affordab|sell your home", 2, "Housing"),
    (r"bill\b|legislat|regulat|\bFTC\b|congress|senate|ordinance|rent control|settle", 2, "Policy"),
]
GEO = [
    (r"arizona|phoenix|scottsdale|chandler|tempe|mesa|glendale|maricopa|pinal|gilbert|\bAZ\b|TSMC", 6, "Arizona"),
    (r"seattle|puget|bellevue|tacoma|washington state|king county|redmond", 6, "Seattle"),
]
# Headlines matching these are dropped unless they also carry a strong
# multifamily signal. Keeps luxury homes, retail, office and lab noise out.
NOISE = re.compile(r"collapse|killed|fatal|luxury|lists (his|her) |estate sets|mansion|celebrity|\bmall\b|retail|stores close|office|\blab\b|life science|data center|self-storage|hotel|winery|restaurant|condo|senior management|tokeniz|crypto|nvidia|skydance|timber", re.I)
OPINION = re.compile(r"^opinion\s*\|", re.I)

FILTERS = ["Multifamily", "REITs", "Capital Markets", "Housing", "Arizona", "Seattle"]
FILTER_MAP = {  # topic -> public filter
    "Multifamily": "Multifamily", "Operations": "Multifamily", "Rents": "Multifamily", "Supply": None,
    "REITs": "REITs",
    "Capital Markets": "Capital Markets", "Rates": "Capital Markets", "Insurance": "Capital Markets",
    "Housing": "Housing", "Policy": "Housing", "Property taxes": "Housing",
    "Employment": None, "Migration": None,
    "Arizona": "Arizona", "Seattle": "Seattle",
}


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def parse_date(s):
    if not s:
        return None
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = email.utils.parsedate_to_datetime(s)
        except Exception:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def canon_url(u):
    p = urlsplit(u.strip())
    return urlunsplit((p.scheme.lower(), p.netloc.lower().replace("www.", ""), p.path.rstrip("/"), "", ""))


def norm_title(t):
    t = html.unescape(t).lower()
    t = re.sub(r"[^a-z0-9$ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def score(item, src):
    text = f"{item['title']} {item.get('desc','')}"
    pts, topics, geo = 0.0, [], []
    for pat, p, name in TOPICS:
        if re.search(pat, text, re.I):
            pts += p
            topics.append(name)
    for pat, p, name in GEO:
        if re.search(pat, text, re.I):
            pts += p
            geo.append(name)
    mf = "Multifamily" in topics
    local_economy = geo and any(t in topics for t in ("Employment", "Supply", "Capital Markets")) or (geo and re.search(r"invest|\$\d", text))
    if NOISE.search(item["title"]) and not mf and not local_economy:
        return None  # irrelevant
    if re.search(r"collapse|killed|fatal", item["title"], re.I):
        return None  # tragedies are not market intelligence
    if not topics and not geo:
        return None
    pts *= src.get("weight", 1.0)
    if src.get("primary_research"):
        pts += 1.5
    age_h = (now_utc() - item["date"]).total_seconds() / 3600
    window = (MAX_AGE_DAYS + 31) if geo else MAX_AGE_DAYS  # local feeds publish slowly
    pts *= max(0.35, 1 - age_h / (window * 24))  # freshness decay
    return round(pts, 2), topics, geo


def build_items(raw_feeds, sources):
    items, dropped = [], {"no_link": 0, "too_old": 0, "irrelevant": 0, "duplicate": 0, "opinion": 0}
    cutoff = now_utc() - dt.timedelta(days=MAX_AGE_DAYS)
    for key, feed in raw_feeds.items():
        src = sources.get(key)
        if not src:
            continue
        for d, title, link, desc in feed.get("items", []):
            date = parse_date(d)
            if not link:
                dropped["no_link"] += 1; continue
            geo_hit = any(re.search(p, title, re.I) for p, _, _ in GEO)
            if not date or date < (cutoff - dt.timedelta(days=31) if geo_hit else cutoff):
                dropped["too_old"] += 1; continue
            if OPINION.search(title):
                dropped["opinion"] += 1; continue
            it = {"title": html.unescape(title).strip(), "link": link.strip(), "date": date, "desc": desc or ""}
            s = score(it, src)
            if s is None:
                dropped["irrelevant"] += 1; continue
            it["score"], it["topics"], it["geo"] = s
            it["source_key"], it["source"], it["access"] = key, src["name"].replace(" Phoenix", ""), src["access"]
            it["public"] = bool(src.get("public"))
            items.append(it)
    # dedupe: same canonical URL, or near-identical headline across sources.
    # Keep the public, higher-scoring copy.
    items.sort(key=lambda i: (i["public"], i["score"]), reverse=True)
    kept, seen_urls = [], set()
    for it in items:
        cu = canon_url(it["link"])
        nt = norm_title(it["title"])
        dup = cu in seen_urls or any(SequenceMatcher(None, nt, norm_title(k["title"])).ratio() > 0.72 for k in kept)
        if not dup:
            # same story, different headline: share a dollar figure and 2+ key words
            money = set(re.findall(r"\$\d+[\d.]*\s?[bmk]?", nt))
            for k in kept:
                km = set(re.findall(r"\$\d+[\d.]*\s?[bmk]?", norm_title(k["title"])))
                common = set(nt.split()) & set(norm_title(k["title"]).split()) - {"the", "a", "in", "for", "of", "to", "and", "plans", "s"}
                if money and money & km and len(common) >= 2:
                    dup = True; k.setdefault("also", []).append(it["source"]); break
        if dup:
            dropped["duplicate"] += 1; continue
        seen_urls.add(cu)
        kept.append(it)
    kept.sort(key=lambda i: i["score"], reverse=True)
    return kept, dropped


def health(raw_feeds, sources, fetched_at):
    rows = []
    for key, src in sources.items():
        f = raw_feeds.get(key, {})
        dates = [parse_date(i[0]) for i in f.get("items", []) if i[0]]
        newest = max(dates) if dates else None
        st = f.get("status")
        if st is None:
            state = "not fetched"
        elif st != 200:
            state = f"error {st}"
        elif not dates:
            state = "empty"
        elif (fetched_at - newest).total_seconds() / 3600 > src["stale_after_h"]:
            state = "stale"
        else:
            state = "healthy"
        rows.append({"key": key, "name": src["name"], "url": src["url"], "access": src["access"],
                     "public": src["public"], "state": state, "items": len(dates),
                     "newest": newest.isoformat() if newest else None, "terms": src["terms"]})
    return rows


def labels(it):
    out = []
    for t in it["topics"] + it["geo"]:
        f = FILTER_MAP.get(t)
        if f and f not in out:
            out.append(f)
    return [f for f in FILTERS if f in out]


def public_item(it, notes):
    n = notes.get(canon_url(it["link"]))
    return {"title": it["title"], "link": it["link"], "source": it["source"],
            "date": it["date"].strftime("%Y-%m-%d"), "access": it["access"],
            "filters": labels(it), "topics": it["topics"][:3], "geo": it["geo"],
            "note": n["note"] if n and (n.get("approved") or SHOW_DRAFTS) else None, "note_status": ("approved" if n and n.get("approved") else "draft") if n else None,
            "also": it.get("also", [])}


# ---------------------------------------------------------------- live fetch
def fetch_live(sources, state_path):
    import urllib.request
    import xml.etree.ElementTree as ET
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    raw = {}
    for key, src in sources["sources"].items():
        if os.environ.get("DESK_PUBLIC_ONLY") == "1" and not src.get("public"):
            continue
        st = state.get(key, {})
        last = st.get("fetched_at", 0)
        if time.time() - last < sources["default_min_interval_minutes"] * 60:
            raw[key] = st.get("cache", {"status": None, "items": []}); continue
        req = urllib.request.Request(src["url"], headers={"User-Agent": sources["user_agent"], "Accept": "application/rss+xml, application/xml;q=0.9"})
        if st.get("etag"): req.add_header("If-None-Match", st["etag"])
        if st.get("modified"): req.add_header("If-Modified-Since", st["modified"])
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read(2_000_000)
                root = ET.fromstring(body)
                items = []
                for it in root.iter("item"):
                    g = lambda t: (it.findtext(t) or "").strip()
                    desc = re.sub(r"<[^>]+>", "", html.unescape(g("description")))[:200]
                    items.append([g("pubDate"), g("title"), g("link"), desc])
                raw[key] = {"status": r.status, "items": items}
                st.update(etag=r.headers.get("ETag"), modified=r.headers.get("Last-Modified"))
        except urllib.error.HTTPError as e:
            raw[key] = st.get("cache", {"status": 200, "items": []}) if e.code == 304 else {"status": e.code, "items": []}
        except Exception as e:
            raw[key] = {"status": f"error: {type(e).__name__}", "items": []}
        st.update(fetched_at=time.time(), cache=raw[key])
        state[key] = st
        time.sleep(max(1, src.get("crawl_delay_s", 1)))
    json.dump(state, open(state_path, "w"))
    return raw


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--live", action="store_true")
    g.add_argument("--snapshot")
    ap.add_argument("--asof", help="treat this ISO time as now (snapshot testing)")
    a = ap.parse_args()
    global now_utc
    if a.asof:
        fixed = parse_date(a.asof); now_utc = lambda: fixed
    sources = json.load(open(os.path.join(HERE, "sources.json")))
    notes_path = os.path.join(HERE, "notes.json")
    notes = json.load(open(notes_path)) if os.path.exists(notes_path) else {}
    if a.live:
        raw = fetch_live(sources, os.path.join(HERE, "state.json")); fetched = now_utc()
    else:
        snap = json.load(open(a.snapshot)); raw = snap["feeds"]; fetched = parse_date(snap["fetched_at"])
    items, dropped = build_items(raw, sources["sources"])
    hl = health(raw, sources["sources"], fetched)
    os.makedirs(OUT, exist_ok=True)
    pub = [public_item(i, notes) for i in items if i["public"]][:30]
    json.dump({"updated": fetched.isoformat(), "filters": FILTERS, "items": pub,
               "sources": [{"name": h["name"], "state": h["state"], "access": h["access"]} for h in hl if h["public"]]},
              open(os.path.join(OUT, "desk.json"), "w"), indent=1)
    shortlist = [{"rank": n + 1, "score": i["score"], "title": i["title"], "source": i["source"], "access": i["access"],
                  "date": i["date"].strftime("%Y-%m-%d"), "link": i["link"], "topics": i["topics"], "geo": i["geo"],
                  "public": i["public"], "also": i.get("also", [])} for n, i in enumerate(items[:15])]
    json.dump({"updated": fetched.isoformat(), "health": hl, "dropped": dropped,
               "kept": len(items), "public_kept": len(pub), "shortlist": shortlist},
              open(os.path.join(OUT, "brief.json"), "w"), indent=1)
    print(f"kept {len(items)} ({len(pub)} public), dropped {dropped}")
    for h in hl:
        print(f"  {h['state']:<12} {h['items']:>3}  {h['name']}  {h['url']}")


if __name__ == "__main__":
    main()
