"""Market Pulse refresh with built-in checks.

Pulls each series straight from FRED's public CSV (St. Louis Fed), checks it,
and writes data/pulse.json. A series that fails any check keeps its last good
value and is flagged, so a bad read never reaches the page.

Checks per series: plausible range, latest date not older than the series
allows, change size, and units (rates in percent, changes in basis points;
vacancy and CPI changes in percentage points).
"""
import csv, datetime as dt, io, json, os, sys, urllib.request

OUT = os.environ.get("PULSE_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pulse.json"))
UA = "TheMultifamilyDesk/1.0 (+https://themultifamilydesk.com; Market Pulse; FRED public CSV)"

SERIES = {
    "DGS10":        {"label": "10 year Treasury", "freq": "Daily", "lo": 0.0, "hi": 10.0, "max_age_d": 7, "max_move": 0.5, "unit": "bp"},
    "SOFR":         {"label": "SOFR", "freq": "Daily", "lo": 0.0, "hi": 10.0, "max_age_d": 7, "max_move": 0.75, "unit": "bp"},
    "MORTGAGE30US": {"label": "30 year mortgage rate", "freq": "Weekly", "lo": 2.0, "hi": 12.0, "max_age_d": 14, "max_move": 0.75, "unit": "bp"},
    "RRVRUSQ156N":  {"label": "U.S. rental vacancy", "freq": "Quarterly", "lo": 3.0, "hi": 15.0, "max_age_d": 200, "max_move": 2.0, "unit": "pt"},
    "CUSR0000SEHA": {"label": "CPI rent", "freq": "Monthly", "lo": 100.0, "hi": 2000.0, "max_age_d": 75, "max_move": None, "unit": "mom"},
}


def fetch(sid):
    start = (dt.date.today() - dt.timedelta(days=800)).isoformat()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read().decode()
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 2 or row[0].lower() in ("date", "observation_date"):
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            continue  # holidays are blank
    return rows


def check(sid, cfg, rows):
    if len(rows) < 3:
        return "too few observations"
    d, v = rows[-1]
    if not (cfg["lo"] <= v <= cfg["hi"]):
        return f"value {v} outside {cfg['lo']} to {cfg['hi']}"
    age = (dt.date.today() - dt.date.fromisoformat(d)).days
    if age > cfg["max_age_d"]:
        return f"latest reading {d} is {age} days old"
    if cfg["max_move"] is not None and abs(v - rows[-2][1]) > cfg["max_move"]:
        return f"move of {v - rows[-2][1]:.2f} is larger than {cfg['max_move']}"
    return None


def build(sid, cfg, rows):
    d, v = rows[-1]
    prev = rows[-2][1]
    item = {"id": sid, "label": cfg["label"], "freq": cfg["freq"], "date": d, "source": "FRED, St. Louis Fed"}
    if cfg["unit"] == "mom":
        item["value"] = round((v / prev - 1) * 100, 1)
        item["display"] = f"{item['value']:+.1f}%"
        item["change_text"] = "month over month"
    else:
        item["value"] = v
        item["display"] = f"{v:.2f}%" if cfg["unit"] == "bp" else f"{v:.1f}%"
        if cfg["unit"] == "bp":
            ch = round((v - prev) * 100)
            item["change"] = ch
            item["change_text"] = "unchanged" if ch == 0 else f"{'+' if ch > 0 else '−'}{abs(ch)} bp"
        else:
            ch = round(v - prev, 1)
            item["change"] = ch
            item["change_text"] = "unchanged" if ch == 0 else f"{'+' if ch > 0 else '−'}{abs(ch):.1f} pt"
        item["spark"] = [x for _, x in rows[-14:]] if cfg["freq"] != "Quarterly" else [x for _, x in rows[-10:]]
    return item


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = {i["id"]: i for i in json.load(open(OUT)).get("series", [])}
        except Exception:
            old = {}
    out, problems = [], []
    for sid, cfg in SERIES.items():
        try:
            rows = fetch(sid)
            err = check(sid, cfg, rows)
        except Exception as e:
            rows, err = [], f"fetch failed: {e}"
        if err:
            problems.append(f"{sid}: {err}")
            if sid in old:
                kept = dict(old[sid]); kept["held"] = err
                out.append(kept)
            continue
        out.append(build(sid, cfg, rows))
    data = {"checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "series": out, "problems": problems}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w"), indent=1)
    print(json.dumps({"ok": len(out) - len([s for s in out if s.get("held")]), "problems": problems}))
    if len(problems) == len(SERIES):
        sys.exit(1)


if __name__ == "__main__":
    main()
