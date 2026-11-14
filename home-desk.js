// Home page: show the three newest top stories from the Market Desk.
(function () {
  var M = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  var E = function (s) { return String(s || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] }) }
  fetch("/data/desk.json", { cache: "no-store" }).then(function (r) { return r.json() }).then(function (d) {
    var box = document.querySelector(".hl"); if (!box || !d.items || d.items.length < 3) return
    var links = box.querySelectorAll("a"); if (links.length < 3) return
    d.items.slice(0, 3).forEach(function (it, i) {
      var p = it.date.split("-"), a = links[i]
      a.href = it.link; a.target = "_blank"; a.rel = "noopener"
      var parts = a.querySelectorAll("div")
      if (parts.length >= 2) { parts[0].innerHTML = E(it.source) + " &#183; " + M[+p[1] - 1] + " " + (+p[2]); parts[1].textContent = it.title }
    })
  }).catch(function () {})
})()
