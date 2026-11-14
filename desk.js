// Loads the latest Market Desk from /api/desk and redraws the list.
// If the request fails, the page keeps the stories it was published with.
(function () {
  var SLUG = function (f) { return f.replace(/ /g, "") }
  var E = function (s) { return String(s || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] }) }
  var M = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  var fdate = function (s) { var p = s.split("-"); return M[+p[1] - 1] + " " + (+p[2]) }
  var tags = function (i) { return i.filters.map(function (f) { return "t-" + SLUG(f) }).join(" ") }
  var chips = function (i) { return i.filters.map(function (f) { return '<span class="chip">' + E(f) + "</span>" }).join("") }
  var access = function (i) { return i.access === "Free" ? '<span class="acc">Free to read</span>' : '<span class="acc pay">' + E(i.access) + "</span>" }
  var note = function (i, big) { return i.note ? '<p class="note"' + (big ? ' style="font-size:18px"' : "") + ">" + E(i.note) + "</p>" : "" }
  var link = function (i) { return '<a class="hd serif" href="' + E(i.link) + '" rel="noopener" target="_blank">' + E(i.title) + "</a>" }

  fetch("/data/desk.json", { cache: "no-store" }).then(function (r) { if (!r.ok) throw 0; return r.json() }).then(function (d) {
    if (!d || !d.items || d.items.length < 5) return
    var feed = document.querySelector(".feed"); if (!feed) return
    var items = d.items.slice(0, 24), lead = items[0], rest = items.slice(1)
    var aside = feed.querySelector(".leadwrap .aside")
    var html = '<div class="leadwrap ' + tags(lead) + '"><div class="lead">' +
      '<div class="meta" style="flex-direction:row;gap:10px;margin-bottom:18px"><span class="src">' + E(lead.source) + '</span><span class="dt">' + fdate(lead.date) + '</span><span class="dt">Top of the desk</span></div>' +
      link(lead) + note(lead, true) + '<div class="chips">' + chips(lead) + "</div></div>" + (aside ? aside.outerHTML : "") + "</div>"
    var counts = {}
    d.filters.forEach(function (f) { counts[f] = items.filter(function (i) { return i.filters.indexOf(f) >= 0 }).length })
    d.filters.forEach(function (f) {
      if (!counts[f]) html += '<div class="empty e-' + SLUG(f) + '">Nothing tagged ' + E(f) + " cleared the desk this cycle. Local stories are kept for up to 45 days, so this fills as the publishers file.</div>"
    })
    rest.forEach(function (i) {
      html += '<article class="row ' + tags(i) + '"><div class="meta"><span class="src">' + E(i.source) + '</span><span class="dt">' + fdate(i.date) + "</span></div><div>" +
        link(i) + note(i) + '<div class="chips">' + chips(i) + '</div></div><div class="ac">' + access(i) + "</div></article>"
    })
    feed.innerHTML = html
    var all = document.querySelector('label[for="f-All"] span'); if (all) all.textContent = items.length
    d.filters.forEach(function (f) { var s = document.querySelector('label[for="f-' + SLUG(f) + '"] span'); if (s) s.textContent = counts[f] })
    var up = new Date(d.updated)
    var txt = "Updated " + up.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZone: "America/Phoenix" }) + " Arizona time"
    document.querySelectorAll("p").forEach(function (p) { if (/^Updated /.test(p.textContent.trim())) p.textContent = txt })
  }).catch(function () {})
})()
// Keep the "Where this comes from" list in step with the feeds that are working.
(function () {
  fetch("/data/desk.json", { cache: "no-store" }).then(function (r) { return r.json() }).then(function (d) {
    var box = document.querySelector(".srclist"); if (!box || !d.sources) return
    var names = {}; d.sources.forEach(function (s) { if (s.state === "healthy") names[s.name.replace(" Phoenix", "")] = 1 })
    var list = Object.keys(names).sort(); if (!list.length) return
    box.innerHTML = list.map(function (n) { return '<span class="dot"></span>' + n.replace(/[&<>]/g, "") }).join("<br>")
  }).catch(function () {})
})()
