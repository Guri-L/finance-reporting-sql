// Draws the charts described by the server. No figures are computed here.
(function () {
  var el = document.getElementById("chart-data");
  if (!el || !window.Chart) return;
  var charts = JSON.parse(el.textContent);
  var palette = ["#2f5d8a", "#9bb7d4", "#c8793a", "#5d8a5f", "#8a6f9e"];
  var fmt = {
    money: function (v) { return v == null ? "" : (v < 0 ? "(" + Math.abs(Math.round(v)).toLocaleString() + ")" : Math.round(v).toLocaleString()); },
    pct: function (v) { return v == null ? "" : v.toFixed(1) + "%"; },
    days: function (v) { return v == null ? "" : v.toFixed(1); },
    ratio: function (v) { return v == null ? "" : v.toFixed(2); }
  };
  var axis = {
    money: function (v) { return Math.abs(v) >= 1e6 ? (v / 1e6).toFixed(1) + "m" : Math.abs(v) >= 1e3 ? (v / 1e3).toFixed(0) + "k" : v; },
    pct: fmt.pct, days: fmt.days, ratio: fmt.ratio
  };
  document.querySelectorAll("canvas[data-chart]").forEach(function (canvas) {
    var c = charts[Number(canvas.dataset.chart)];
    new Chart(canvas, {
      type: c.kind,
      data: {
        labels: c.labels,
        datasets: c.datasets.map(function (d, i) {
          var colour = palette[i % palette.length];
          return { label: d.label, data: d.data, type: d.type || c.kind,
                   backgroundColor: colour, borderColor: colour, borderWidth: (d.type || c.kind) === "line" ? 2 : 0,
                   pointRadius: 2, tension: 0.2, order: (d.type === "line") ? 0 : 1 };
        })
      },
      options: {
        maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { position: "bottom" },
                   tooltip: { callbacks: { label: function (ctx) { return ctx.dataset.label + ": " + fmt[c.unit](ctx.parsed.y); } } } },
        scales: { x: { stacked: c.stacked, grid: { display: false } },
                  y: { stacked: c.stacked, ticks: { callback: axis[c.unit] } } }
      }
    });
  });
})();
