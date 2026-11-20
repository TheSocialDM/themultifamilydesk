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
    if sid == "DGS10":
        # Count straight daily closes above 5.00%, newest first, from the full checked series.
        n, since = 0, None
        for d0, x in reversed(rows):
            if x > 5.0:
                n += 1; since = d0
            else:
                break
        item["streak_above5"] = n
        item["streak_since"] = since
    return item


# Local readings shown in the Pillar markets tile (not on FRED). Update here when a newer release is out.
LOCAL = {
    "phx_renewal": -2.4, "us_renewal": 1.7, "phx_period": "Sep 2026",
    "sea_vacancy": 6.6, "sea_yoy": -0.4, "sea_period": "Q3 2026",
    # Cap rate spread (IPA State of the Market, Q3 2026, via CRE Daily Oct 23 2026). Quarterly: update when IPA's Q4 report is out.
    "cap_quarters": 17, "cap_since": 1990, "cap_period": "Q3 2026",
    "cap_link": "https://www.credaily.com/briefs/multifamily-recovery-slows-as-apartment-sales-fall-6/",
}


def bp(n):
    return f"{abs(n)} basis point{'s' if abs(n) != 1 else ''}"


def desk_read(by):
    """Plain language read of what each move means for owners and operators.
    Rule based, explains meaning only, never forecasts. No dashes in copy."""
    out = []
    t = by.get("DGS10")
    if t and not t.get("held"):
        v, ch, sp = t["value"], t.get("change", 0), t.get("spark") or []
        n = len(sp)
        if ch >= 5:
            lead = f"The 10 year Treasury rose {bp(ch)} from the prior reading to {v:.2f}%" + (f", its highest in the last {n} readings." if sp and v >= max(sp) else ".")
        elif ch <= -5:
            lead = f"The 10 year Treasury fell {bp(ch)} from the prior reading to {v:.2f}%" + (f", its lowest in the last {n} readings." if sp and v <= min(sp) else ".")
        else:
            lead = f"The 10 year Treasury was little changed at {v:.2f}%."
        base = " Permanent loan rates are priced as a spread over this benchmark, and cap rates tend to follow it over time"
        if v >= 5:
            mean = base + ", so a sustained level above 5% weighs on values and refinancing for loans coming due."
        elif ch <= -5:
            mean = base + ", so lower long rates ease pressure on values and refinancing."
        else:
            mean = base + "."
        st = t.get("streak_above5", 0)
        if st >= 2:
            lead = lead + f" That makes {st} straight closes above 5%."
        out.append({"label": "Debt costs", "text": lead + mean})
    L = LOCAL
    above = t and not t.get("held") and t["value"] > 5
    out.append({"label": "Valuations", "text": f"Apartment cap rates have sat close to the 10 year Treasury for {L['cap_quarters']} straight quarters, the longest run in IPA data back to {L['cap_since']} (IPA, {L['cap_period']}). " + ("With the 10 year above 5% and little spread left, values depend more on rent and income growth than on falling rates." if above else "With little spread left, values depend more on rent and income growth than on falling rates.")})
    s = by.get("SOFR")
    if s and not s.get("held"):
        v, ch = s["value"], s.get("change", 0)
        if abs(ch) <= 3:
            txt = f"SOFR was little changed at {v:.2f}%, so the base rate on floating rate loans held roughly flat."
        elif ch > 0:
            txt = f"SOFR rose {bp(ch)} to {v:.2f}%, raising the base rate on floating rate loans, which weighs most on properties without rate caps."
        else:
            txt = f"SOFR fell {bp(ch)} to {v:.2f}%, lowering the base rate on floating rate loans."
        out.append({"label": "Floating rate loans", "text": txt})
    m = by.get("MORTGAGE30US")
    if m and not m.get("held"):
        v, ch = m["value"], m.get("change", 0)
        move = f"eased {bp(ch)} to" if ch < 0 else (f"rose {bp(ch)} to" if ch > 0 else "held at")
        if v >= 6.5:
            txt = f"The 30 year mortgage rate {move} {v:.2f}%. Rates at this level keep homeownership costly for many renters, which tends to support renewals."
        else:
            txt = f"The 30 year mortgage rate {move} {v:.2f}%. Lower rates make buying more realistic for some renters, so move outs to purchase are worth tracking."
        out.append({"label": "Renter demand", "text": txt})
    r = by.get("RRVRUSQ156N")
    if r and not r.get("held"):
        v, ch = r["value"], r.get("change", 0)
        q = "Q" + str((int(r["date"][5:7]) - 1) // 3 + 1)
        if ch > 0:
            txt = f"The national rental vacancy rate (Census, all rental housing) rose {abs(ch):.1f} points to {v:.1f}% in {q}. Higher vacancy gives renters more leverage, and concessions are typically most common at properties still leasing up."
        elif ch < 0:
            txt = f"The national rental vacancy rate (Census, all rental housing) fell {abs(ch):.1f} points to {v:.1f}% in {q}. Lower vacancy gives operators more room on renewals and concessions."
        else:
            txt = f"The national rental vacancy rate (Census, all rental housing) held at {v:.1f}% in {q}."
        out.append({"label": "Vacancy", "text": txt})
    c = by.get("CUSR0000SEHA")
    if c and not c.get("held"):
        v = c["value"]
        mon = ["January","February","March","April","May","June","July","August","September","October","November","December"][int(c["date"][5:7]) - 1]
        word = "rose" if v > 0 else ("fell" if v < 0 else "was flat")
        amt = f" {abs(v):.1f}%" if v != 0 else ""
        txt = f"Rent of primary residence {word}{amt} in {mon}. This measure includes existing leases, so it trails changes in asking rents by several months."
        out.append({"label": "Rent inflation", "text": txt})
    L = LOCAL
    out.append({"label": "Phoenix and Seattle", "text": f"Phoenix renewal rents are {'down' if L['phx_renewal'] < 0 else 'up'} {abs(L['phx_renewal']):.1f}%, against a {abs(L['us_renewal']):.1f}% {'gain' if L['us_renewal'] >= 0 else 'decline'} for the U.S. (Yardi, {L['phx_period']}), consistent with ongoing supply pressure. Seattle apartment vacancy {'fell' if L['sea_yoy'] < 0 else 'rose'} to {L['sea_vacancy']:.1f}%, {'down' if L['sea_yoy'] < 0 else 'up'} {abs(L['sea_yoy']):.1f} points from a year earlier (Kidder Mathews, {L['sea_period']})."})
    watch = []
    if t and not t.get("held"):
        watch.append("whether the 10 year holds above 5%" if t["value"] >= 5 else "whether the 10 year stays below 5%")
    watch += ["the next weekly mortgage rate on Thursday", "the next CPI rent reading"]
    txt = ", ".join(watch[:-1]) + ", and " + watch[-1] + "."
    out.append({"label": "What to watch", "text": txt[0].upper() + txt[1:]})
    return out


def marketing_read(by):
    """Marketing and leasing lens for Michael's page. Meaning only, no forecasts, no dashes."""
    out = []
    t = by.get("DGS10")
    if t and not t.get("held"):
        v = t["value"]
        if v >= 4.5:
            txt = f"With the 10 year Treasury at {v:.2f}%, owners are paying more for debt, so marketing budgets get a harder look. The plans that hold up show which leases each dollar produced."
        else:
            txt = f"With the 10 year Treasury at {v:.2f}%, debt pressure on owners is easing, which opens room for marketing that compounds, like reputation and search."
        out.append({"label": "Owner budgets", "text": txt})
    m = by.get("MORTGAGE30US")
    if m and not m.get("held"):
        v = m["value"]
        if v >= 6.5:
            txt = f"At {v:.2f}%, the 30 year mortgage keeps buying out of reach for many renters. Renewals and referrals carry more weight, so the resident experience is part of the marketing plan."
        else:
            txt = f"At {v:.2f}%, buying is more realistic for some renters. Retention marketing and renewal offers matter more when buying is within reach."
        out.append({"label": "Renter demand", "text": txt})
    r = by.get("RRVRUSQ156N")
    if r and not r.get("held"):
        v, ch = r["value"], r.get("change", 0)
        if ch >= 0:
            txt = f"National rental vacancy is {v:.1f}%, so renters have options and compare more communities before they tour. The communities that show up first in Google, Maps and AI answers get the first look."
        else:
            txt = f"National rental vacancy fell to {v:.1f}%. With fewer choices, renters decide faster, so accurate listings, fast replies and strong reviews close the gap between a search and a tour."
        out.append({"label": "Leasing competition", "text": txt})
    c = by.get("CUSR0000SEHA")
    if c and not c.get("held"):
        v = c["value"]
        mon = ["January","February","March","April","May","June","July","August","September","October","November","December"][int(c["date"][5:7]) - 1]
        if v >= 0.4:
            txt = f"Rent of primary residence rose {v:.1f}% in {mon}. Firm rent growth rewards communities whose reputation and presentation justify the price."
        else:
            txt = f"Rent of primary residence rose {v:.1f}% in {mon}, a modest pace. When pricing power is limited, reputation, reviews and presentation carry more of the leasing load." if v > 0 else f"Rent of primary residence was flat or lower in {mon}. When pricing power is limited, reputation, reviews and presentation carry more of the leasing load."
        out.append({"label": "Pricing power", "text": txt})
    out.append({"label": "What to watch", "text": "How AI assistants answer apartment questions in your market. Being seen is not the same as being chosen, and that gap can cost tours."})
    return out


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
    data = {"checked": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "series": out, "problems": problems,
            "read": desk_read({i["id"]: i for i in out}),
            "read_marketing": marketing_read({i["id"]: i for i in out}),
            "local": {k: LOCAL[k] for k in ("cap_quarters", "cap_since", "cap_period", "cap_link")}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w"), indent=1)
    print(json.dumps({"ok": len(out) - len([s for s in out if s.get("held")]), "problems": problems}))
    if len(problems) == len(SERIES):
        sys.exit(1)


if __name__ == "__main__":
    main()
