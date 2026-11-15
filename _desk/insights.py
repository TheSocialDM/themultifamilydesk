"""Keep data/insights.json in step with the thesocialdm.com blog.

Runs inside the hourly market-desk job. Adds any new multifamily post from the
blog RSS feed (published after the cutoff below) to the top of the Insights
library on /michael/. Never removes or rewrites existing entries. Posts that
were left out on purpose stay out (data/insights_exclude.json). If the feed
cannot be read, the file is left untouched.
"""
import json, re, sys, urllib.request, html
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

FEED = "https://www.thesocialdm.com/blog/rss.xml"
OUT = "data/insights.json"
EXCLUDE = "data/insights_exclude.json"
CUTOFF = datetime(2026, 11, 15, tzinfo=timezone.utc)
TOPIC = re.compile(r"apartment|multifamily|renter|leas(e|ing)|property manag|resident|communit", re.I)
UNVERIFIED = re.compile(r"\b(93%|80%|billion)\b")


def clean(t, n=230):
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    t = re.sub(r"\s+[–—-]\s+", ", ", re.sub(r"\s+", " ", t)).strip()
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0].rstrip(",.;:") + "."
    return t


def main():
    try:
        req = urllib.request.Request(FEED, headers={"User-Agent": "Mozilla/5.0 (MultifamilyDesk insights sync)"})
        raw = urllib.request.urlopen(req, timeout=30).read()
        root = ET.fromstring(raw)
    except Exception as e:
        print("insights: feed unreadable, left as is:", e)
        return 0
    data = json.load(open(OUT))
    items = data.get("items", [])
    have = {x["url"].rstrip("/") for x in items}
    try:
        skip = {u.rstrip("/") for u in json.load(open(EXCLUDE))}
    except Exception:
        skip = set()
    new = []
    for it in root.findall(".//item"):
        url = (it.findtext("link") or "").strip().rstrip("/")
        title = clean(it.findtext("title"), 140)
        dek = clean(it.findtext("description"))
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if not url or url in have or url in skip or pub < CUTOFF:
            continue
        if not TOPIC.search(title + " " + dek) or UNVERIFIED.search(title + " " + dek):
            continue
        new.append({"title": title, "url": url, "dek": dek, "date": pub.date().isoformat()})
    if not new:
        print("insights: nothing new")
        return 0
    new.sort(key=lambda x: x["date"], reverse=True)
    data["items"] = new + items
    data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=False)
    print("insights: added", len(new), [x["title"] for x in new])
    return 0


if __name__ == "__main__":
    sys.exit(main())
