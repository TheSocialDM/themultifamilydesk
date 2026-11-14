// Market Pulse: redraws the rate tiles and ticker from /data/pulse.json,
// which a scheduled job refreshes from FRED with range, date and size checks.
(function () {
  var MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDate(s, freq) {
    var p = s.split("-"), y = +p[0], m = +p[1] - 1, d = +p[2];
    if (freq === "Quarterly") return "Q" + (Math.floor(m / 3) + 1) + " " + y;
    if (freq === "Monthly") return MON[m] + " " + y;
    return MON[m] + " " + d + ", " + y;
  }
  function spark(svg, vals) {
    if (!svg || !vals || vals.length < 2) return;
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), r = hi - lo || 1, n = vals.length;
    var pts = vals.map(function (v, i) {
      return [(4 + i * 232 / (n - 1)).toFixed(1), (52 - (v - lo) / r * 48).toFixed(1)];
    });
    var pl = svg.querySelector("polyline"), c = svg.querySelector("circle");
    if (pl) pl.setAttribute("points", pts.map(function (p) { return p.join(","); }).join(" "));
    if (c) { c.setAttribute("cx", pts[n - 1][0]); c.setAttribute("cy", pts[n - 1][1]); }
  }
  fetch("/data/pulse.json", { cache: "no-store" }).then(function (r) { return r.json(); }).then(function (d) {
    var by = {};
    d.series.forEach(function (s) { by[s.label] = s; });
    document.querySelectorAll(".mpt").forEach(function (t) {
      var lab = t.firstElementChild && t.firstElementChild.textContent.trim();
      var s = by[lab];
      if (!s) return;
      var row = t.querySelector(".rise");
      var spans = row ? row.querySelectorAll("span") : [];
      if (spans[0]) spans[0].textContent = s.display;
      if (spans[1] && s.change_text) {
        spans[1].textContent = s.change_text;
        // Rising rates and vacancy are a headwind for owners: red up, green down.
        spans[1].style.color = s.held || !s.change ? "#c9cdd2" : (s.change > 0 ? "#ff8a80" : "#7fd8a6");
      }
      spark(t.querySelector("svg"), s.spark);
      var foot = t.querySelector("svg") && t.querySelector("svg").nextElementSibling;
      if (foot) {
        var extra = lab === "SOFR" ? " · the rate that replaced LIBOR" : "";
        foot.textContent = s.freq + " · " + fmtDate(s.date, s.freq) + (s.held ? " · update delayed, last good reading" : extra);
      }
    });
    // Ticker: update the rate entries in place.
    var names = { "10 year Treasury": "10 year Treasury", "SOFR": "SOFR", "30 year mortgage": "30 year mortgage rate", "Rental vacancy": "U.S. rental vacancy", "CPI rent": "CPI rent" };
    document.querySelectorAll(".tick > span").forEach(function (sp) {
      var b = sp.querySelector("span"), meta = sp.querySelectorAll("span")[1];
      if (!b) return;
      var s = by[names[b.textContent.trim()]];
      if (!s) return;
      var when = s.freq === "Weekly" ? "week of " + fmtDate(s.date, s.freq).replace(/, \d{4}$/, "") : fmtDate(s.date, s.freq).replace(/, \d{4}$/, "");
      if (b.nextSibling) b.nextSibling.textContent = "  " + s.display + "  ";
      if (meta) meta.textContent = (s.id === "CUSR0000SEHA" ? "month over month" : s.change_text) + " · " + when;
    });
    document.querySelectorAll("div").forEach(function (el) {
      if (el.children.length === 1 && /^Checked /.test(el.textContent.trim())) {
        var t = new Date(d.checked);
        var old = Date.now() - t.getTime() > 36 * 3600 * 1000;
        el.lastChild.textContent = (old ? "Last checked " : "Checked ") + MON[t.getMonth()] + " " + t.getDate() + ", " + t.getFullYear();
        var dot = el.querySelector(".dot"); if (dot && (old || (d.problems && d.problems.length))) dot.style.background = "#c9cdd2";
      }
    });
  }).catch(function () {});
})();
