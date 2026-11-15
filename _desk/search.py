"""AI Search Watch: newest public headlines on how Google and AI assistants
find and recommend local businesses. RSS only (headline, source, date, link),
article pages are never requested. Writes data/search.json.

A run that finds fewer than 3 relevant stories keeps the previous file, so the
page never empties. Each source failing is recorded, never fatal.
"""
import datetime as dt, email.utils, html, json, os, re, sys, urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SEARCH_OUT", os.path.join(HERE, "..", "data", "search.json"))
UA = "TheMultifamilyDesk/1.0 (+https://themultifamilydesk.com; AI Search Watch; RSS reader)"
MAX_AGE_DAYS = 21
KEEP = 6

SOURCES = [
    ("Google Search Central", "https://developers.google.com/search/blog/feed.xml", 1.4),
    ("Google Search Central", "https://feeds.feedburner.com/blogspot/amDG", 1.4),
    ("Search Engine Land", "https://searchengineland.com/feed", 1.0),
    ("Search Engine Roundtable", "https://www.seroundtable.com/index.xml", 0.9),
    ("Search Engine Journal", "https://www.searchenginejournal.com/feed/", 0.9),
]

STRONG = re.compile(r"AI Overview|AI Mode|ChatGPT|Gemini|Perplexity|Copilot|\bLLMs?\b|answer engine|\bAEO\b|\bGEO\b|generative|AI search|AI assistant|Google Business Profile|\bGBP\b|Google Maps|local search|local pack|map pack|reviews?\b|Business Profile", re.I)
LOCAL = re.compile(r"local|Maps|Business Profile|\bGBP\b|reviews?\b|near me|map pack|local pack", re.I)
NOISE = re.compile(r"webinar|sponsored|podcast|\bjobs?\b|hiring|\bPPC\b|Google Ads|Microsoft Ads|Amazon|shopping ads|ecommerce|e-commerce|Merchant Center|your products|PMax|Performance Max|bidding|daily brief|week in review|recap|SMX", re.I)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def text(el, *names):
    for n in names:
        x = el.find(n)
        if x is not None:
            return (x.text or x.get("href") or "").strip()
    return ""


def parse(raw):
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = []
    for it in root.iter("item"):
        items.append((text(it, "title"), text(it, "link"), text(it, "pubDate")))
    for it in root.findall(".//a:entry", ns):
        link = ""
        for l in it.findall("a:link", ns):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
        items.append((text(it, "a:title".replace("a:", "{http://www.w3.org/2005/Atom}")), link,
                      text(it, "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated")))
    return items


def when(s):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).astimezone(dt.timezone.utc)
    except Exception:
        pass
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception:
        return None


def main():
    now = dt.datetime.now(dt.timezone.utc)
    seen, picked, health = set(), [], []
    for name, url, w in SOURCES:
        try:
            rows = parse(fetch(url))
            health.append({"source": name, "url": url, "ok": True, "items": len(rows)})
        except Exception as e:
            health.append({"source": name, "url": url, "ok": False, "error": str(e)[:120]})
            continue
        for title, link, pub in rows:
            title = html.unescape(re.sub(r"\s+", " ", title)).strip()
            title = re.sub(r"\s+via\s+@\S+(,\s*@\S+)*\s*$", "", title).strip()
            d = when(pub)
            if not title or not link or not d or (now - d).days > MAX_AGE_DAYS:
                continue
            if not STRONG.search(title) or NOISE.search(title):
                continue
            key = re.sub(r"[^a-z0-9]", "", title.lower())[:60]
            if key in seen:
                continue
            seen.add(key)
            score = w + (0.8 if LOCAL.search(title) else 0) - (now - d).days * 0.05
            picked.append({"title": title, "link": link, "source": name, "date": d.date().isoformat(), "_s": score})
    picked.sort(key=lambda x: (-x["_s"], x["date"]))
    top = sorted(picked[:KEEP], key=lambda x: x["date"], reverse=True)
    for x in top:
        x.pop("_s", None)
    if len(top) < 3:
        print(json.dumps({"kept_previous": True, "found": len(top), "health": health}))
        return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"updated": now.isoformat(timespec="seconds"), "items": top, "health": health}, open(OUT, "w"), indent=1)
    print(json.dumps({"ok": len(top), "health": health}))


if __name__ == "__main__":
    main()
