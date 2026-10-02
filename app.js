/* Desk Dashboard — carga datos.json y pinta KPIs / top10 / sectores / earnings / ranking */
(function () {
  "use strict";

  var AUTO_MS = 5 * 60 * 1000;
  var state = {
    ranking: [],
    logos: {},
    earnings: [],
    rsWeekly: null,
    kind: "",
    sector: "",
    sectorLabel: "",
    sectors: null,
    flags: { above_ema200: false, rs_gt_70: false, solo_verdes: false },
    search: "",
    autoTimer: null,
    loading: false,
    ready: false,
    loadError: "",
    fichaSym: null,
    listScroll: 0,
    baseTitle: "",
    walkforward: null,
    historial: null,
    patternTab: "breakout_52w",
    patternScan: null,
    page: "resumen",
    rrg: null,
    rrgFilter: "sector",
    rrgFrame: 0,
    rrgTimer: null,
    signalsBlock: null,
  };

  var HEALTH_SPECS = [
    { key: "pe_ttm", label: "P/E", kind: "ratio" },
    { key: "revenue_growth_yoy", label: "Ingresos", kind: "pct" },
    { key: "eps_growth_yoy", label: "EPS", kind: "pct" },
    { key: "gross_margin", label: "Margen bruto", kind: "pct" },
    { key: "operating_margin", label: "Margen op.", kind: "pct" },
    { key: "net_margin", label: "Margen neto", kind: "pct" },
    { key: "roe", label: "ROE", kind: "pct" },
    { key: "debt_equity", label: "Deuda/patrimonio", kind: "ratio" },
    { key: "current_ratio", label: "Liquidez", kind: "ratio" },
    { key: "pb", label: "P/B", kind: "ratio" },
    { key: "dividend_yield", label: "Dividendo", kind: "pct" },
  ];

  var PILLAR_SPEC = [
    { key: "tendencia", label: "Tendencia", max: 30 },
    { key: "fuerza_rs", label: "Fuerza RS", max: 35 },
    { key: "contraccion", label: "Contracción", max: 35 },
  ];

  var SCORE_PENALTY = {
    extendido_vs_ema200: 5,
    posible_distribucion: 4,
    atr_elevado: 3,
  };

  var RS_CAPTION_FALLBACK =
    "RS Score semanal: percentil 0–100 de (retorno del ticker − retorno de SPY) en ~126 sesiones (6 meses; si no alcanza, 63 sesiones), recalculado al último cierre de cada una de las últimas 16 semanas ISO. No incluye el bonus de aceleración del pilar Fuerza RS. El último punto es el RS Score del ranking.";

  function fmtPct(n) {
    if (n == null || Number.isNaN(n)) return "—";
    return (Math.round(n * 10) / 10) + "%";
  }

  function fmtNum(n, digits) {
    if (n == null || Number.isNaN(n)) return "—";
    return Number(n).toFixed(digits == null ? 1 : digits);
  }

  function distClass(n) {
    if (n == null) return "";
    return n >= 0 ? "dd-num-pos" : "dd-num-neg";
  }

  function scoreTierClass(n) {
    if (n == null || Number.isNaN(n)) return "";
    if (n >= 70) return " dd-score-high";
    if (n >= 45) return " dd-score-mid";
    return " dd-score-low";
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }


  /* ---- Logos: círculo claro + fallback con iniciales (gradiente naranja) ---- */
  function logoFor(r) {
    if (!r) return null;
    if (r.logo) return r.logo;
    var sym = String(r.symbol || "").toUpperCase();
    return (state.logos && state.logos[sym]) || null;
  }

  function tickerInitials(sym) {
    var s = String(sym || "").replace(/[^A-Za-z0-9]/g, "").toUpperCase();
    return s.slice(0, s.length > 3 ? 2 : Math.min(2, s.length)) || "?";
  }

  function logoHtml(sym, src, size) {
    var px = size || 20;
    var ini = escapeHtml(tickerInitials(sym));
    var lg = px > 24 ? " dd-tlogo-lg" : "";
    if (!src) {
      return '<span class="dd-tlogo dd-tlogo-fallback' + lg + '" aria-hidden="true">' + ini + "</span>";
    }
    return (
      '<span class="dd-tlogo' + lg + '" aria-hidden="true" data-initials="' + ini + '">' +
      '<img src="' + escapeHtml(src) + '" alt="" loading="lazy" decoding="async" width="' + px + '" height="' + px + '" />' +
      "</span>"
    );
  }

  function markRowLink(tr, symbol) {
    if (!symbol) return;
    tr.tabIndex = 0;
    tr.setAttribute("role", "link");
    tr.setAttribute("aria-label", "Ver ficha de " + symbol);
  }

  /** Ticker con logo a la izquierda. cls = clase del texto (dd-ticker / dd-earn-sym). */
  function tickerWithLogo(r, cls) {
    var sym = (r && r.symbol) || "";
    return (
      '<span class="dd-ticker-wrap">' + logoHtml(sym, logoFor(r)) +
      '<span class="' + (cls || "dd-ticker") + '">' + escapeHtml(sym || "?") + "</span></span>"
    );
  }

  // onerror delegado (capture): errores de <img> no burbujean, pero sí se capturan.
  document.addEventListener(
    "error",
    function (ev) {
      var img = ev.target;
      if (!img || img.tagName !== "IMG" || !img.parentNode) return;
      var wrap = img.parentNode;
      if (!wrap.classList || !wrap.classList.contains("dd-tlogo")) return;
      wrap.classList.add("dd-tlogo-fallback");
      wrap.textContent = wrap.getAttribute("data-initials") || "?";
    },
    true
  );

  function getRegime(data) {
    return data.regime || data.regime_stub || null;
  }

  function renderKpis(data) {
    var k = data.kpis || {};
    setText("kpi-activos", String(k.activos != null ? k.activos : "—"));
    setText("kpi-ema200", String(k.above_ema200 != null ? k.above_ema200 : "—"));
    setText("kpi-ema200-pct", k.above_ema200_pct != null ? fmtPct(k.above_ema200_pct) : "");
    setText("kpi-sma50", String(k.above_sma50 != null ? k.above_sma50 : "—"));
    setText("kpi-sma50-pct", k.above_sma50_pct != null ? fmtPct(k.above_sma50_pct) : "");
    setText("kpi-rs70", String(k.rs_gt_70 != null ? k.rs_gt_70 : "—"));
    setText("kpi-rs70-pct", k.rs_gt_70_pct != null ? fmtPct(k.rs_gt_70_pct) : "");
    setText("kpi-vol", String(k.volumen_inusual != null ? k.volumen_inusual : "—"));
    setText("kpi-vol-pct", k.volumen_inusual_pct != null ? fmtPct(k.volumen_inusual_pct) : "");

    var reg = getRegime(data);
    var label = (reg && reg.label) || "—";
    setText("kpi-regime", label);
    var sub = "";
    if (reg && reg.pct_above_ema200 != null) {
      sub = Math.round(reg.pct_above_ema200 * 10) / 10 + "% sobre EMA200";
    }
    setText("kpi-regime-sub", sub);

    var card = document.getElementById("kpi-regime-card");
    if (card) {
      card.setAttribute("data-regime", label === "—" ? "" : label);
    }

    var when = fmtArt(data.generated_at);
    setText("generated-at", when || data.generated_at || "—");
    var stamp = document.getElementById("generated-at");
    if (stamp && data.generated_at) stamp.setAttribute("datetime", data.generated_at);
  }


  function fmtSignedPct(n) {
    if (n == null || Number.isNaN(n)) return "—";
    var v = Math.round(n * 10) / 10;
    var s = (v > 0 ? "+" : "") + v + "%";
    return s;
  }

  function sparklineSvg(values) {
    if (!values || values.length < 2) {
      return '<span class="dd-spark-empty">—</span>';
    }
    var nums = values.map(Number).filter(function (x) { return !Number.isNaN(x); });
    if (nums.length < 2) return '<span class="dd-spark-empty">—</span>';
    var min = Math.min.apply(null, nums);
    var max = Math.max.apply(null, nums);
    var span = max - min || 1;
    var w = 88;
    var h = 28;
    var pad = 2;
    var pts = nums.map(function (v, i) {
      var x = pad + (i / (nums.length - 1)) * (w - pad * 2);
      var y = pad + (1 - (v - min) / span) * (h - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    var up = nums[nums.length - 1] >= nums[0];
    var cls = up ? "dd-spark-up" : "dd-spark-down";
    return (
      '<svg class="dd-spark ' + cls + '" viewBox="0 0 ' + w + ' ' + h +
      '" width="' + w + '" height="' + h + '" aria-hidden="true">' +
      '<polyline fill="none" stroke="currentColor" stroke-width="1.75" ' +
      'stroke-linecap="round" stroke-linejoin="round" points="' + pts + '" />' +
      "</svg>"
    );
  }

  function entroHtml(entro) {
    if (!entro || !entro.label) {
      return '<span class="dd-entro dd-entro-empty">—</span>';
    }
    var parts = String(entro.label).split(" · ");
    var dateLine = parts[0] || "";
    var sessLine = parts.slice(1).join(" · ");
    return (
      '<span class="dd-entro" title="' + escapeHtml(entro.label) + '">' +
      '<span class="dd-entro-date">' + escapeHtml(dateLine) + "</span>" +
      (sessLine
        ? '<span class="dd-entro-sessions">' + escapeHtml(sessLine) + "</span>"
        : "") +
      "</span>"
    );
  }

  function entroInline(entro) {
    if (!entro || !entro.label) {
      return '<span class="dd-entro-inline dd-entro-empty">—</span>';
    }
    return (
      '<span class="dd-entro-inline" title="' + escapeHtml(entro.label) + '">' +
      escapeHtml(entro.label) +
      "</span>"
    );
  }

  function returnBarHtml(pct) {
    if (pct == null || Number.isNaN(pct)) {
      return '<span class="dd-ret-empty">—</span>';
    }
    var abs = Math.min(Math.abs(pct), 25);
    var width = Math.max(4, (abs / 25) * 100);
    var dir = pct >= 0 ? "pos" : "neg";
    return (
      '<div class="dd-ret-cell">' +
      '<span class="dd-ret-pct dd-num-' + dir + '">' + escapeHtml(fmtSignedPct(pct)) + "</span>" +
      '<span class="dd-ret-track" aria-hidden="true">' +
      '<span class="dd-ret-bar dd-ret-bar-' + dir + '" style="width:' + width.toFixed(1) + '%"></span>' +
      "</span></div>"
    );
  }

  function renderTop10(block) {
    var avgEl = document.getElementById("top10-avg");
    var spyEl = document.getElementById("top10-spy");
    var body = document.getElementById("top10-body");
    var sub = document.getElementById("top10-subtitle");
    var section = document.querySelector('[data-section="top10-return"]');
    if (!body) return;

    if (!block || !block.rows || !block.rows.length) {
      if (avgEl) avgEl.textContent = "—";
      if (spyEl) spyEl.textContent = "—";
      body.innerHTML = "";
      var tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6" class="dd-empty">Sin datos de retorno Top 10. Ejecutá patch_top10_return.py o build.py.</td>';
      body.appendChild(tr);
      if (section) section.setAttribute("data-ready", "0");
      return;
    }

    var win = block.window_sessions != null ? block.window_sessions : 10;
    if (sub) sub.textContent = "Retorno últimas " + win + " ruedas";

    if (avgEl) {
      avgEl.textContent = fmtSignedPct(block.avg_return_pct);
      avgEl.className = "dd-kpi-value " + distClass(block.avg_return_pct);
    }
    if (spyEl) {
      spyEl.textContent = fmtSignedPct(block.spy_return_pct);
      spyEl.className = "dd-kpi-value " + distClass(block.spy_return_pct);
    }

    body.innerHTML = "";
    block.rows.forEach(function (r) {
      var tr = document.createElement("tr");
      tr.setAttribute("data-symbol", r.symbol || "");
      markRowLink(tr, r.symbol);
      tr.innerHTML =
        '<td class="dd-col-rank" data-col="rank">' + escapeHtml(r.rank != null ? r.rank : "") + "</td>" +
        '<td class="dd-col-ticker" data-col="ticker">' + tickerWithLogo(r, "dd-ticker") + "</td>" +
        '<td data-col="entro" class="dd-col-entro">' + entroHtml(r.entro) + "</td>" +
        '<td data-col="spark" class="dd-col-spark">' + sparklineSvg(r.spark) + "</td>" +
        '<td data-col="score"><span class="dd-score' +
        scoreTierClass(r.desk_score) +
        '">' +
        fmtNum(r.desk_score, 1) +
        "</span></td>" +
        '<td data-col="return">' + returnBarHtml(r.return_pct) + "</td>";
      body.appendChild(tr);
    });
    if (section) section.setAttribute("data-ready", "1");
  }

  function fmtSignedPct2(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Math.round(Number(n) * 100) / 100;
    var body = Math.abs(v).toFixed(2);
    if (v > 0) return "+" + body + "%";
    if (v < 0) return "-" + body + "%";
    return "0.00%";
  }

  function fmtIso(iso) {
    if (!iso || String(iso).length < 10) return iso || "—";
    return String(iso).slice(8, 10) + "/" + String(iso).slice(5, 7) + "/" + String(iso).slice(0, 4);
  }

  function setSignedValue(id, n) {
    var el = document.getElementById(id);
    if (!el) return;
    el.textContent = fmtSignedPct2(n);
    el.className = "dd-kpi-value " + distClass(n);
  }

  function drawWalkforwardChart(block) {
    var host = document.getElementById("wf-chart");
    if (!host) return;
    var curve = (block && block.curve) || [];
    if (curve.length < 2) {
      host.innerHTML = "";
      host.setAttribute("aria-label", "Sin curva de la simulación");
      return;
    }
    var width = Math.round(host.clientWidth || (host.parentNode && host.parentNode.clientWidth) || 0);
    if (width < 40) {
      host._wfRetry = (host._wfRetry || 0) + 1;
      if (host._wfRetry < 6) {
        window.requestAnimationFrame(function () { drawWalkforwardChart(block); });
      }
      return;
    }
    host._wfRetry = 0;
    var height = width < 560 ? 200 : 236;
    var padL = 46;
    var padR = 12;
    var padT = 14;
    var padB = 26;
    var vals = [];
    curve.forEach(function (p) {
      vals.push(Number(p.portfolio), Number(p.spy));
    });
    var minV = Math.min.apply(null, vals);
    var maxV = Math.max.apply(null, vals);
    if (minV === maxV) {
      minV -= 1;
      maxV += 1;
    }
    var span = maxV - minV;
    minV -= span * 0.08;
    maxV += span * 0.08;
    function xAt(i) {
      if (curve.length === 1) return padL;
      return padL + (i / (curve.length - 1)) * (width - padL - padR);
    }
    function yAt(v) {
      return padT + (1 - (v - minV) / (maxV - minV)) * (height - padT - padB);
    }
    function poly(key) {
      return curve.map(function (p, i) {
        return xAt(i).toFixed(1) + "," + yAt(Number(p[key])).toFixed(1);
      }).join(" ");
    }
    var ticks = [maxV, (maxV + minV) / 2, minV];
    var grid = ticks.map(function (v) {
      var y = yAt(v).toFixed(1);
      var label = Math.abs(v) >= 100 ? String(Math.round(v)) : (Math.round(v * 10) / 10).toFixed(1);
      return (
        '<line x1="' + padL + '" y1="' + y + '" x2="' + (width - padR) + '" y2="' + y + '" stroke="rgba(255,255,255,0.08)" stroke-width="1"></line>' +
        '<text x="' + (padL - 8) + '" y="' + y + '" text-anchor="end" dominant-baseline="middle">' + escapeHtml(label) + "</text>"
      );
    }).join("");
    var baseLine = "";
    if (100 >= minV && 100 <= maxV) {
      var yb = yAt(100).toFixed(1);
      baseLine =
        '<line x1="' + padL + '" y1="' + yb + '" x2="' + (width - padR) + '" y2="' + yb +
        '" stroke="rgba(255,255,255,0.28)" stroke-width="1" stroke-dasharray="4 4"></line>';
    }
    var areaPts =
      xAt(0).toFixed(1) + "," + yAt(Number(curve[0].portfolio)).toFixed(1) + " " +
      poly("portfolio") + " " +
      xAt(curve.length - 1).toFixed(1) + "," + (height - padB).toFixed(1) + " " +
      xAt(0).toFixed(1) + "," + (height - padB).toFixed(1);
    var last = curve[curve.length - 1];
    var first = curve[0];
    var xLabels =
      '<text x="' + xAt(0).toFixed(1) + '" y="' + (height - 8) + '" text-anchor="start">' + escapeHtml(fmtIso(first.date)) + "</text>" +
      '<text x="' + xAt(curve.length - 1).toFixed(1) + '" y="' + (height - 8) + '" text-anchor="end">' + escapeHtml(fmtIso(last.date)) + "</text>";
    var dot =
      '<circle cx="' + xAt(curve.length - 1).toFixed(1) + '" cy="' + yAt(Number(last.portfolio)).toFixed(1) + '" r="3.2" fill="#FF6B35"></circle>' +
      '<circle cx="' + xAt(curve.length - 1).toFixed(1) + '" cy="' + yAt(Number(last.spy)).toFixed(1) + '" r="3" fill="#7EB6FF"></circle>';
    host.innerHTML =
      '<svg viewBox="0 0 ' + width + " " + height + '" width="' + width + '" height="' + height + '" role="presentation">' +
      grid + baseLine +
      '<polygon points="' + areaPts + '" fill="rgba(255,107,53,0.14)" stroke="none"></polygon>' +
      '<polyline fill="none" stroke="#7EB6FF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="' + poly("spy") + '"></polyline>' +
      '<polyline fill="none" stroke="#FF6B35" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" points="' + poly("portfolio") + '"></polyline>' +
      dot + xLabels +
      "</svg>";
    var portLbl = fmtSignedPct2(block.total_return_pct);
    var spyLbl = fmtSignedPct2(block.spy_total_return_pct);
    host.setAttribute(
      "aria-label",
      "Curva base 100. Cartera " + portLbl + ", SPY " + spyLbl +
      ", del " + fmtIso(first.date) + " al " + fmtIso(last.date) + "."
    );
  }

  function renderWalkforward(block) {
    state.walkforward = block || null;
    var sub = document.getElementById("wf-subtitle");
    var caption = document.getElementById("wf-caption");
    var body = document.getElementById("wf-body");
    if (caption && block && block.note) caption.textContent = block.note;

    function clearKpis() {
      ["wf-port", "wf-spy", "wf-excess", "wf-dd", "wf-dd-spy"].forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = "—";
        el.className = "dd-kpi-value";
      });
      setText("wf-beat", "—");
      setText("wf-beat-sub", "");
      setText("wf-weeks", "—");
      setText("wf-turn", "—");
      setText("wf-turn-sub", "");
    }

    if (!block || !block.weeks) {
      clearKpis();
      if (sub) sub.textContent = "Walk-forward semanal · base 100";
      drawWalkforwardChart(null);
      if (body) {
        body.innerHTML = '<tr><td colspan="4" class="dd-empty">Sin simulación todavía. Se calcula al correr build.py.</td></tr>';
      }
      return;
    }

    if (sub && block.window_start && block.window_end) {
      sub.textContent = "Del " + fmtIso(block.window_start) + " al " + fmtIso(block.window_end) + " · base 100";
    }
    setSignedValue("wf-port", block.total_return_pct);
    setSignedValue("wf-spy", block.spy_total_return_pct);
    setSignedValue("wf-excess", block.excess_return_pct);
    setSignedValue("wf-dd", block.max_drawdown_pct);
    setSignedValue("wf-dd-spy", block.spy_max_drawdown_pct);
    setText("wf-beat", block.weeks_beat_spy + "/" + block.weeks);
    setText("wf-beat-sub", block.weeks_beat_spy_pct != null ? fmtPct(block.weeks_beat_spy_pct) : "");
    setText("wf-weeks", String(block.weeks));
    if (block.avg_names_changed == null) {
      setText("wf-turn", "—");
      setText("wf-turn-sub", "");
    } else {
      setText("wf-turn", fmtNum(block.avg_names_changed, 2));
      setText("wf-turn-sub", "nombres que salen / semana");
    }
    drawWalkforwardChart(block);

    if (!body) return;
    body.innerHTML = "";
    var rows = block.recent || [];
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="4" class="dd-empty">Sin semanas para mostrar.</td></tr>';
      return;
    }
    rows.forEach(function (r) {
      var tr = document.createElement("tr");
      var changed = r.names_changed == null ? "—" : String(r.names_changed);
      tr.innerHTML =
        '<td>' + escapeHtml(fmtIso(r.date)) + "</td>" +
        '<td class="' + distClass(r.portfolio_return_pct) + '">' + escapeHtml(fmtSignedPct2(r.portfolio_return_pct)) + "</td>" +
        '<td class="' + distClass(r.spy_return_pct) + '">' + escapeHtml(fmtSignedPct2(r.spy_return_pct)) + "</td>" +
        "<td>" + escapeHtml(changed) + "</td>";
      body.appendChild(tr);
    });
  }

  function hourLabel(hour) {
    var h = String(hour || "").toLowerCase();
    if (h === "amc") return "después del cierre";
    if (h === "bmo") return "antes de abrir";
    if (h === "dmh") return "durante la rueda";
    return hour || "";
  }

  function earnEpsLine(e) {
    if (!e) return "";
    var bits = [];
    if (e.epsActual != null && e.epsActual !== "") {
      bits.push("EPS " + fmtEsNum(e.epsActual, 2));
    } else if (e.epsEstimate != null && e.epsEstimate !== "") {
      bits.push("EPS est. " + fmtEsNum(e.epsEstimate, 2));
    }
    if (e.revenueActual != null && e.revenueActual !== "") {
      bits.push("ingresos " + fmtUsdCompact(e.revenueActual));
    } else if (e.revenueEstimate != null && e.revenueEstimate !== "") {
      bits.push("ingresos est. " + fmtUsdCompact(e.revenueEstimate));
    }
    return bits.join(" · ");
  }

  function renderEarnings(list) {
    var strip = document.getElementById("earnings-strip");
    if (!strip) return;
    strip.innerHTML = "";
    if (!list || !list.length) {
      var p = document.createElement("p");
      p.className = "dd-empty";
      p.textContent = "Sin earnings esta semana en el universo (o Finnhub no disponible).";
      strip.appendChild(p);
      return;
    }
    list.forEach(function (e) {
      var chip = document.createElement("div");
      chip.className = "dd-earn-chip";
      chip.setAttribute("data-symbol", e.symbol || "");
      if (e.hour) chip.setAttribute("data-hour", e.hour);
      var spoken = hourLabel(e.hour);
      var dateLabel = e.date ? fmtDayMonth(e.date) : "";
      var eps = earnEpsLine(e);
      var tip = [e.symbol, e.date, e.hour].filter(Boolean).join(" · ");
      chip.title = tip;
      chip.innerHTML =
        tickerWithLogo(e, "dd-earn-sym") +
        (dateLabel ? '<span class="dd-earn-date">' + escapeHtml(dateLabel) + "</span>" : "") +
        (spoken ? '<span class="dd-earn-hour">' + escapeHtml(spoken) + "</span>" : "") +
        (eps ? '<span class="dd-earn-eps">' + escapeHtml(eps) + "</span>" : "");
      strip.appendChild(chip);
    });
  }

  function filteredRanking() {
    var q = (state.search || "").trim().toUpperCase();
    return state.ranking.filter(function (r) {
      if (state.kind && r.kind !== state.kind) return false;
      if (state.sector) {
        if (r.sector !== state.sector) return false;
        if (String(r.kind || "").toLowerCase() === "etf") return false;
      }
      if (state.flags.above_ema200 && !r.above_ema200) return false;
      if (state.flags.rs_gt_70 && !((r.rs_score || 0) > 70)) return false;
      if (state.flags.solo_verdes && !(r.entry && r.entry.verdict === "verde")) return false;
      if (q && String(r.symbol || "").toUpperCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function updateFilterCount(shown, total) {
    var extra = state.sector ? " · " + (state.sectorLabel || state.sector) : "";
    setText("filter-count", "Mostrando " + shown + " de " + total + extra);
  }


  var FLAG_LABELS = {
    extendido_vs_ema200: "Extendido",
    atr_elevado: "ATR alto",
    posible_distribucion: "Distribución",
    rsi_sobrecompra: "RSI alto",
    rsi_sobreventa: "RSI bajo",
  };

  function insiderBadgeHtml(row) {
    var ins = row && row.insiders;
    if (!ins || !ins.notable) return "";
    return (
      '<span class="dd-flag dd-flag-insider" data-flag="insider_buy" title="Compras netas de insiders, últimos 90 días">Insiders</span>'
    );
  }

  function luzHtml(row) {
    var entry = row && row.entry;
    if (!entry || !entry.verdict) return '<span class="dd-flags-empty">—</span>';
    var label = entry.label || entry.verdict;
    return (
      '<span class="dd-luz" data-verdict="' + escapeHtml(entry.verdict) +
      '" title="' + escapeHtml(label) + '" role="img" aria-label="' + escapeHtml(label) + '"></span>'
    );
  }

  function buyPctHtml(row) {
    if (String((row && row.kind) || "").toLowerCase() === "etf") {
      return '<span class="dd-flags-empty" title="Los ETF no tienen recomendaciones de analistas">—</span>';
    }
    var a = row && row.analysts;
    if (!a || a.buy_pct == null) return '<span class="dd-flags-empty">—</span>';
    var tip = (a.total != null ? a.total + " analistas. " : "") + (a.trend_label || "");
    return (
      '<span class="dd-buy-pct" title="' + escapeHtml(tip.trim()) + '">' +
      escapeHtml(fmtEsSmart(a.buy_pct, 1)) + "%</span>"
    );
  }

  function formatFlags(flags, extraHtml) {
    var items = flags || [];
    if (!items.length && !extraHtml) {
      return '<span class="dd-flags-empty">—</span>';
    }
    var body = items
      .map(function (f) {
        var label = FLAG_LABELS[f] || f;
        return (
          '<span class="dd-flag" data-flag="' +
          escapeHtml(f) +
          '" title="' +
          escapeHtml(f) +
          '">' +
          escapeHtml(label) +
          "</span>"
        );
      })
      .join("");
    return '<span class="dd-flags">' + body + (extraHtml || "") + "</span>";
  }

  function renderRanking(rows) {
    var tbody = document.getElementById("ranking-body");
    if (!tbody) return;
    tbody.innerHTML = "";
    (rows || []).forEach(function (r) {
      var p = r.pillars || {};
      var tr = document.createElement("tr");
      tr.setAttribute("data-symbol", r.symbol || "");
      tr.setAttribute("data-score", r.desk_score != null ? r.desk_score : "");
      tr.setAttribute("data-kind", r.kind || "");
      markRowLink(tr, r.symbol);

      var dist = r.dist_ema200_pct;
      var cells = [
        r.rank != null ? r.rank : "",
        tickerWithLogo(r, "dd-ticker"),
        luzHtml(r),
        buyPctHtml(r),
        '<span class="dd-score' + scoreTierClass(r.desk_score) + '">' + fmtNum(r.desk_score, 1) + "</span>",
        entroInline(r.entro),
        formatFlags(r.flags, insiderBadgeHtml(r)),
        fmtNum(p.tendencia, 1),
        fmtNum(r.rs_score, 1),
        fmtNum(p.contraccion, 1),
        '<span class="' + distClass(dist) + '">' + (dist == null ? "—" : fmtNum(dist, 2) + "%") + "</span>",
        fmtNum(r.vol_rel_20d, 2),
        '<span class="dd-kind" data-kind="' + escapeHtml(r.kind || "") + '">' + escapeHtml(r.kind || "") + "</span>",
      ];

      cells.forEach(function (html, i) {
        var td = document.createElement("td");
        td.innerHTML = html;
        if (i === 0) {
          td.setAttribute("data-col", "rank");
          td.className = "dd-sticky-col dd-col-rank";
        }
        if (i === 1) {
          td.setAttribute("data-col", "ticker");
          td.className = "dd-sticky-col dd-col-ticker";
        }
        if (i === 2) {
          td.setAttribute("data-col", "luz");
          td.className = "dd-col-luz";
        }
        if (i === 3) {
          td.setAttribute("data-col", "compra");
          td.className = "dd-col-compra";
        }
        if (i === 4) td.setAttribute("data-col", "score");
        if (i === 5) td.setAttribute("data-col", "entro");
        if (i === 6) td.setAttribute("data-col", "flags");
        if (i === 7) td.setAttribute("data-col", "tendencia");
        if (i === 8) td.setAttribute("data-col", "rs");
        if (i === 9) td.setAttribute("data-col", "contraccion");
        if (i === 10) td.setAttribute("data-col", "dist_ema200");
        if (i === 11) td.setAttribute("data-col", "vol_rel");
        if (i === 12) td.setAttribute("data-col", "kind");
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
  }

  function applyFilters() {
    var filtered = filteredRanking();
    renderRanking(filtered);
    updateFilterCount(filtered.length, state.ranking.length);
  }

  function renderNotes(notes) {
    var ul = document.getElementById("notes-list");
    if (!ul) return;
    ul.innerHTML = "";
    (notes || []).forEach(function (n) {
      var li = document.createElement("li");
      li.textContent = n;
      ul.appendChild(li);
    });
  }

  function fail(msg) {
    state.ready = true;
    state.loadError = msg;
    setText("generated-at", "Error");
    var strip = document.getElementById("earnings-strip");
    if (strip) {
      strip.innerHTML = "";
      var p = document.createElement("p");
      p.className = "dd-empty";
      p.textContent = msg;
      strip.appendChild(p);
    }
    var resumenText = document.getElementById("resumen-text");
    if (resumenText) resumenText.textContent = msg;
    renderRoute();
  }

  function markUiRefreshOk() {
    var el = document.getElementById("last-ui-refresh");
    if (!el) return;
    var now = new Date();
    var hh = String(now.getHours()).padStart(2, "0");
    var mm = String(now.getMinutes()).padStart(2, "0");
    var ss = String(now.getSeconds()).padStart(2, "0");
    el.hidden = false;
    el.textContent = "· " + hh + ":" + mm;
  }

  function setLoading(on) {
    state.loading = !!on;
    var btn = document.getElementById("btn-refresh");
    if (!btn) return;
    btn.disabled = !!on;
    btn.classList.toggle("is-loading", !!on);
    btn.textContent = on ? "Actualizando…" : "Actualizar";
  }

  function sectorLabelFor(sector) {
    var rows = (state.sectors && state.sectors.rows) || [];
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].sector === sector) return rows[i].label || sector;
    }
    return sector || "";
  }

  function syncSectorActive() {
    var current = state.sector || "";
    document.querySelectorAll(".dd-sector-card").forEach(function (card) {
      var on = !!current && card.getAttribute("data-sector") === current;
      card.classList.toggle("is-active", on);
      var btn = card.querySelector(".dd-sector-select");
      if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    var group = document.querySelector('.dd-filter-group[data-filter="sector"]');
    if (!group) return;
    group.querySelectorAll(".dd-chip").forEach(function (btn) {
      var key = btn.getAttribute("data-sector") || "";
      var on = key === current;
      btn.classList.toggle("is-active", on);
      if (on && current && btn.scrollIntoView) {
        btn.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    });
  }

  function setSectorFilter(sector, scroll) {
    var next = sector || "";
    if (next && next === state.sector) next = "";
    state.sector = next;
    state.sectorLabel = next ? sectorLabelFor(next) : "";
    syncSectorActive();
    applyFilters();
    if (scroll && state.sector) {
      if ((location.hash || "") === "#ranking") {
        var el = document.getElementById("ranking");
        if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        location.hash = "#ranking";
      }
    }
  }

  function renderSectorFilters(rows) {
    var group = document.querySelector('.dd-filter-group[data-filter="sector"]');
    if (!group) return;
    var known = {};
    (rows || []).forEach(function (r) {
      if (r && r.sector) known[r.sector] = r.label || r.sector;
    });
    if (state.sector && !known[state.sector]) {
      state.sector = "";
      state.sectorLabel = "";
    } else if (state.sector) {
      state.sectorLabel = known[state.sector];
    }
    group.innerHTML = "";
    var all = document.createElement("button");
    all.type = "button";
    all.className = "dd-chip" + (state.sector ? "" : " is-active");
    all.setAttribute("data-sector", "");
    all.textContent = "Todos";
    group.appendChild(all);
    (rows || []).forEach(function (r) {
      if (!r || !r.sector) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "dd-chip" + (r.sector === state.sector ? " is-active" : "");
      btn.setAttribute("data-sector", r.sector);
      btn.textContent = r.label || r.sector;
      group.appendChild(btn);
    });
  }

  function trendHtml(item) {
    var trend = item.rs_trend;
    var delta = item.rs_delta;
    var cls = "dd-sector-trend";
    var arrow = "—";
    var word = "sin historia de RS";
    if (trend === "up") {
      cls += " is-up";
      arrow = "▲";
      word = "RS en alza";
    } else if (trend === "down") {
      cls += " is-down";
      arrow = "▼";
      word = "RS en baja";
    } else if (trend === "flat") {
      cls += " is-flat";
      arrow = "→";
      word = "RS sin cambio";
    }
    var num = "";
    if (delta != null && !Number.isNaN(Number(delta))) {
      var v = Math.round(Number(delta) * 10) / 10;
      num = " " + (v > 0 ? "+" : "") + v;
    }
    var title =
      word +
      (item.rs_now != null ? " · ahora " + fmtNum(item.rs_now, 1) : "") +
      (item.rs_weeks_ago != null ? " · hace 4 sem " + fmtNum(item.rs_weeks_ago, 1) : "");
    return (
      '<span class="' + cls + '" title="' + escapeHtml(title) + '">' +
      '<span class="dd-sr-only">' + escapeHtml(word) + "</span>" +
      '<span aria-hidden="true">' + arrow + num + "</span></span>"
    );
  }

  function renderSectors(block) {
    state.sectors = block || null;
    var grid = document.getElementById("sector-grid");
    var caption = document.getElementById("sector-caption");
    var note = document.getElementById("sector-note");
    var rows = (block && block.rows) || [];
    if (caption && block && block.caption) caption.textContent = block.caption;
    if (note) {
      var summary = block && block.excluded && block.excluded.summary;
      if (summary) note.textContent = summary;
    }
    renderSectorFilters(rows);
    if (!grid) return;
    grid.innerHTML = "";
    if (!rows.length) {
      var empty = document.createElement("p");
      empty.className = "dd-empty";
      empty.textContent = "Sin agregados por sector. Se calculan al correr build.py.";
      grid.appendChild(empty);
      return;
    }
    rows.forEach(function (item) {
      var card = document.createElement("article");
      card.className = "dd-sector-card" + (item.sector === state.sector ? " is-active" : "");
      card.setAttribute("data-sector", item.sector || "");
      card.setAttribute("role", "listitem");
      var heat = item.avg_desk_score == null ? 0 : Math.max(0, Math.min(100, Number(item.avg_desk_score))) / 100;
      card.style.setProperty("--heat", String(heat));
      var tier = scoreTierClass(item.avg_desk_score).trim();
      var best = item.best || {};
      var bestSym = best.symbol || "";
      var low = item.low_sample
        ? '<span class="dd-sector-low" title="1 o 2 nombres: el promedio se mueve con cualquiera de ellos.">Muestra chica</span>'
        : "";
      var barW = item.avg_desk_score == null ? 0 : Math.max(0, Math.min(100, Number(item.avg_desk_score)));
      card.innerHTML =
        '<div class="dd-sector-top">' +
        '<button type="button" class="dd-sector-select" aria-pressed="' +
        (item.sector === state.sector ? "true" : "false") + '">' +
        '<span class="dd-sector-name">' + escapeHtml(item.label || item.sector || "—") + "</span>" +
        '<span class="dd-sector-count">' + escapeHtml(String(item.count)) +
        (item.count === 1 ? " nombre" : " nombres") + "</span>" +
        "</button>" +
        trendHtml(item) +
        "</div>" +
        (low ? '<div class="dd-sector-badges">' + low + "</div>" : "") +
        '<div class="dd-sector-bar ' + tier + '" aria-hidden="true"><span style="width:' + barW + '%"></span></div>' +
        '<dl class="dd-sector-metrics">' +
        '<div><dt>Desk</dt><dd class="' + tier + '">' + fmtNum(item.avg_desk_score, 1) + "</dd></div>" +
        '<div><dt>RS</dt><dd>' + fmtNum(item.avg_rs_score, 1) + "</dd></div>" +
        '<div><dt>Sobre EMA200</dt><dd>' + fmtPct(item.pct_above_ema200) + "</dd></div>" +
        '<div><dt>Top 10</dt><dd>' + escapeHtml(String(item.top10_count != null ? item.top10_count : "—")) + "</dd></div>" +
        '<div><dt>Cambio día</dt><dd class="' + distClass(item.avg_change_pct) + '">' + fmtSignedPct2(item.avg_change_pct) + "</dd></div>" +
        "</dl>" +
        '<p class="dd-sector-best">Mejor ' +
        (bestSym
          ? '<a class="dd-sector-link" href="#/t/' + encodeURIComponent(bestSym) + '">' +
            escapeHtml(bestSym) + "</a>"
          : "—") +
        (best.desk_score != null ? ' <span class="dd-sector-best-score">' + fmtNum(best.desk_score, 1) + "</span>" : "") +
        "</p>";
      grid.appendChild(card);
    });
  }

  function fmtMetric(kind, n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    if (kind === "pct") return fmtEsSmart(n, 1) + "%";
    return fmtEsSmart(n, 1);
  }

  function fmtShares(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Number(n);
    if (v > 0) return "+" + fmtEsNum(v, 0);
    return fmtEsNum(v, 0);
  }

  function fmtUsdShort(n) {
    if (n == null || Number.isNaN(Number(n))) return "";
    var v = Number(n);
    var sign = v < 0 ? "−" : "";
    var a = Math.abs(v);
    if (a >= 1000000) return sign + "USD " + fmtEsSmart(a / 1000000, 1) + " millones";
    if (a >= 1000) return sign + "USD " + fmtEsSmart(a / 1000, 0) + " mil";
    return sign + "USD " + fmtEsSmart(a, 0);
  }

  function fmtArt(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    try {
      return (
        new Intl.DateTimeFormat("es-AR", {
          timeZone: "America/Argentina/Buenos_Aires",
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hour12: false,
        }).format(d) + " ART"
      );
    } catch (e) {
      return String(iso);
    }
  }

  function linkRow(item, extraText) {
    var sym = (item && item.symbol) || "";
    var score = item && item.desk_score != null ? fmtEsSmart(item.desk_score, 1) : "—";
    return (
      '<a class="dd-link-row" href="#/t/' + encodeURIComponent(sym) + '">' +
      logoHtml(sym, logoFor(item), 22) +
      '<span class="dd-link-sym">' + escapeHtml(sym) + "</span>" +
      '<span class="dd-link-score">Desk ' + escapeHtml(score) + "</span>" +
      '<span class="dd-link-extra">' + escapeHtml(extraText || "") + "</span></a>"
    );
  }

  function renderResumen(data) {
    var block = data && data.resumen;
    var when = document.getElementById("resumen-when");
    var text = document.getElementById("resumen-text");
    if (!text) return;
    if (!block || !block.text) {
      if (when) when.textContent = "";
      text.textContent = "Sin resumen en esta publicación. Se arma al correr build.py.";
      var emptyBtn = document.getElementById("resumen-more");
      if (emptyBtn) emptyBtn.hidden = true;
      return;
    }
    if (when) {
      var stamp = fmtArt(block.generated_at || data.generated_at);
      when.textContent = stamp || block.headline || "";
      if (block.generated_at) when.setAttribute("datetime", block.generated_at);
    }
    text.textContent = block.text;
    text.classList.remove("is-open");
    text.classList.add("is-clamped");
    syncClamp("resumen-text", "resumen-more");
  }

  function renderInsiders(block) {
    var root = document.getElementById("insider-list");
    var cap = document.getElementById("insider-caption");
    if (cap && block && block.caption) cap.textContent = block.caption;
    if (!root) return;
    var rows = (block && block.rows) || [];
    if (!rows.length) {
      root.innerHTML =
        '<p class="dd-empty">Sin compras netas de insiders para mostrar. Si recién arranca, los datos se completan de a poco para no pasarnos del límite de Finnhub.</p>';
      return;
    }
    root.innerHTML = rows
      .map(function (r) {
        var bits = [];
        if (r.net_shares != null) bits.push(fmtShares(r.net_shares) + " acc.");
        if (r.buyers != null) bits.push(r.buyers === 1 ? "1 compró" : r.buyers + " compraron");
        if (r.net_value_usd != null) bits.push(fmtUsdShort(r.net_value_usd) + (r.value_approx ? " aprox." : ""));
        return linkRow(r, bits.join(" · "));
      })
      .join("");
  }

  function renderPatterns(block) {
    state.patternScan = block || null;
    var tabs = document.getElementById("pattern-tabs");
    var list = document.getElementById("pattern-list");
    var groups = (block && block.groups) || [];
    if (!groups.length) {
      if (tabs) tabs.innerHTML = "";
      if (list) list.innerHTML = '<p class="dd-empty">Sin patrones en esta publicación.</p>';
      return;
    }
    if (!groups.some(function (g) { return g.id === state.patternTab; })) {
      state.patternTab = groups[0].id;
    }
    if (tabs) {
      tabs.innerHTML = groups
        .map(function (g) {
          var on = g.id === state.patternTab;
          return (
            '<button type="button" class="dd-chip' + (on ? " is-active" : "") +
            '" role="tab" aria-selected="' + (on ? "true" : "false") +
            '" data-pattern="' + escapeHtml(g.id) + '">' +
            escapeHtml(g.label || g.id) + " · " + g.count + "</button>"
          );
        })
        .join("");
    }
    var group = groups.filter(function (g) { return g.id === state.patternTab; })[0] || groups[0];
    if (!list) return;
    var hits = (group && group.rows) || [];
    if (!hits.length) {
      list.innerHTML = '<p class="dd-empty">Ningún nombre cumple este patrón hoy.</p>';
      return;
    }
    list.innerHTML = hits
      .map(function (r) {
        return linkRow(r, r.detail || "");
      })
      .join("");
  }

  function bindPatternTabs() {
    var panel = document.getElementById("pattern-panel");
    if (!panel) return;
    panel.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-pattern]");
      if (!btn || !panel.contains(btn)) return;
      state.patternTab = btn.getAttribute("data-pattern") || state.patternTab;
      renderPatterns(state.patternScan);
    });
  }

  function patternChips(row) {
    var pats = (row && row.patterns) || [];
    if (!pats.length) {
      return '<p class="dd-ficha-empty">Sin patrones del escáner en esta rueda.</p>';
    }
    return (
      '<div class="dd-pat-chips">' +
      pats
        .map(function (p) {
          return (
            '<span class="dd-pat-chip" title="' + escapeHtml(p.detail || "") + '">' +
            escapeHtml(p.label || p.id || "") + "</span>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function healthBlock(row) {
    var head = '<section class="dd-ficha-card" aria-label="Salud de la empresa"><h2 class="dd-ficha-kicker">Salud de la empresa</h2>';
    if (String((row && row.kind) || "").toLowerCase() === "etf") {
      return head + '<p class="dd-ficha-empty">Sin datos. Los ETF no tienen fundamentos de empresa.</p></section>';
    }
    var fund = row && row.fundamentals;
    var metrics = (fund && fund.metrics) || {};
    var vs = (fund && fund.vs_sector) || {};
    var cells = [];
    HEALTH_SPECS.forEach(function (spec) {
      var value = metrics[spec.key];
      if (value == null || value === "") return;
      var cmp = vs[spec.key] || {};
      var line = spec.label + " " + fmtMetric(spec.kind, value);
      if (cmp.median != null && cmp.n >= 3) {
        line += " vs " + fmtMetric(spec.kind, cmp.median) + " del sector";
      }
      var cue = cmp.cue || "";
      var cueWord = cue === "green" ? "mejor que el sector" : cue === "red" ? "peor que el sector" : cue === "amber" ? "en línea con el sector" : "";
      cells.push(
        '<div class="dd-health-item" data-cue="' + escapeHtml(cue) + '">' +
        "<span>" + escapeHtml(line) + "</span>" +
        (cueWord ? '<span class="dd-health-cue">' + escapeHtml(cueWord) + "</span>" : "") +
        "</div>"
      );
    });
    var body = cells.length
      ? '<div class="dd-health-grid">' + cells.join("") + "</div>"
      : '<p class="dd-ficha-empty">Sin datos</p>';
    return (
      head + body +
      '<p class="dd-ficha-note">Informativo. No entra en el Desk Score.</p></section>'
    );
  }

  function insiderFichaBlock(row) {
    var head = '<section class="dd-ficha-card" aria-label="Qué compran los grandes"><h2 class="dd-ficha-kicker">Qué compran los grandes</h2>';
    if (String((row && row.kind) || "").toLowerCase() === "etf") {
      return head + '<p class="dd-ficha-empty">Sin datos. Los ETF no tienen operaciones de insiders.</p></section>';
    }
    var ins = row && row.insiders;
    if (!ins || (ins.net_shares == null && ins.open_market_count == null)) {
      return head + '<p class="dd-ficha-empty">Sin datos</p></section>';
    }
    var money = ins.net_value_usd == null ? "" : " · " + fmtUsdShort(ins.net_value_usd) + (ins.value_approx ? " aprox." : "");
    var latest = ins.latest_date ? " · última " + fmtDayMonth(ins.latest_date) : "";
    var summary =
      "Neto " + fmtShares(ins.net_shares) + " acciones · " +
      (ins.buyers || 0) + " compraron y " + (ins.sellers || 0) + " vendieron" +
      money + latest;
    var txs = ins.transactions || [];
    var list;
    if (!txs.length) {
      list = '<p class="dd-ficha-empty">Sin operaciones de mercado abierto en los últimos 90 días.</p>';
    } else {
      list =
        '<ul class="dd-ins-tx">' +
        txs
          .map(function (t) {
            var sell = t.side === "sell";
            var role = t.role ? '<span class="dd-ins-role">' + escapeHtml(t.role) + "</span>" : "";
            return (
              "<li><span class=\"dd-ins-name\">" + escapeHtml(t.name || "Sin nombre") + "</span>" +
              role +
              '<span class="dd-ins-side ' + (sell ? "is-sell" : "is-buy") + '">' +
              (sell ? "Venta" : "Compra") + "</span>" +
              '<span class="dd-ins-shares">' + escapeHtml(t.shares == null ? "—" : fmtEsNum(t.shares, 0)) + "</span>" +
              '<span class="dd-ins-px">' + escapeHtml(t.price == null ? "—" : fmtPrice(t.price)) + "</span>" +
              '<span class="dd-ins-date">' + escapeHtml(fmtDayMonth(t.date)) + "</span></li>"
            );
          })
          .join("") +
        "</ul>";
    }
    var excluded = ins.excluded_count
      ? '<p class="dd-ficha-note">Quedaron afuera ' + escapeHtml(String(ins.excluded_count)) +
        " movimientos que no son de mercado abierto (premios, ejercicios y similares).</p>"
      : "";
    return head + '<p class="dd-ficha-entro">' + escapeHtml(summary) + "</p>" + list + excluded + "</section>";
  }

  var ANALYST_SEGS = [
    { key: "strong_buy", label: "Compra fuerte", cls: "dd-an-sb" },
    { key: "buy", label: "Compra", cls: "dd-an-b" },
    { key: "hold", label: "Mantener", cls: "dd-an-h" },
    { key: "sell", label: "Venta", cls: "dd-an-s" },
    { key: "strong_sell", label: "Venta fuerte", cls: "dd-an-ss" },
  ];

  function entryBlock(row) {
    var entry = row && row.entry;
    if (!entry || !entry.verdict) {
      return (
        '<section class="dd-ficha-card dd-entry-card" aria-label="Semáforo de riesgo">' +
        '<h2 class="dd-ficha-kicker">Semáforo de riesgo</h2>' +
        '<p class="dd-ficha-empty">Sin semáforo en esta publicación. Se calcula al correr build.py.</p>' +
        historialFichaLine(row && row.symbol) +
        "</section>"
      );
    }
    var items = (entry.checks || []).map(function (c) {
      var ok = !!c.ok;
      return (
        '<li class="' + (ok ? "is-ok" : "is-bad") + '">' +
        '<span class="dd-entry-mark" aria-hidden="true">' + (ok ? "✓" : "✗") + "</span>" +
        '<span><strong>' + escapeHtml(c.label || "") + ".</strong> " + escapeHtml(c.reason || "") + "</span></li>"
      );
    }).join("");
    var disclaimer = entry.disclaimer || "Alerta de riesgo automática. El verde no es una señal de compra.";
    return (
      '<section class="dd-ficha-card dd-entry-card" data-verdict="' + escapeHtml(entry.verdict) +
      '" aria-label="Semáforo de riesgo">' +
      '<h2 class="dd-ficha-kicker">Semáforo de riesgo</h2>' +
      '<div class="dd-entry-head">' +
      '<span class="dd-entry-light" data-verdict="' + escapeHtml(entry.verdict) +
      '" role="img" aria-label="' + escapeHtml(entry.label || "") + '"></span>' +
      '<p class="dd-entry-label">' + escapeHtml(entry.label || "") + "</p></div>" +
      historialFichaLine(row.symbol) +
      '<ul class="dd-entry-checks">' + items + "</ul>" +
      '<p class="dd-entry-disclaimer">' + escapeHtml(disclaimer) + "</p></section>"
    );
  }

  function analystPeriod(iso) {
    var s = String(iso || "");
    if (s.length < 10) return "—";
    return s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4);
  }

  function analystBlock(row) {
    var head = '<section class="dd-ficha-card" aria-label="Opinión de los analistas"><h2 class="dd-ficha-kicker">Opinión de los analistas</h2>';
    var note = '<p class="dd-ficha-note">Los analistas suelen ser optimistas y reaccionan tarde. Es contexto, no señal.</p>';
    if (String((row && row.kind) || "").toLowerCase() === "etf") {
      return head + '<p class="dd-ficha-empty">Sin datos. Los ETF no tienen recomendaciones de analistas.</p></section>';
    }
    var a = row && row.analysts;
    if (!a) {
      return head + '<p class="dd-ficha-empty">Sin datos todavía. Se completa de a poco para no pasarnos del límite de Finnhub.</p></section>';
    }
    var latest = a.latest;
    if (!latest || !latest.total) {
      return head + '<p class="dd-ficha-empty">Sin recomendaciones publicadas para este nombre.</p>' + note + "</section>";
    }
    var total = Number(latest.total) || 0;
    var bar = ANALYST_SEGS.map(function (seg) {
      var n = Number(latest[seg.key]) || 0;
      if (!n || !total) return "";
      var pct = (n / total) * 100;
      return (
        '<span class="dd-an-seg ' + seg.cls + '" style="width:' + pct.toFixed(2) +
        '%" title="' + escapeHtml(seg.label + ": " + n) + '"></span>'
      );
    }).join("");
    var legend = ANALYST_SEGS.map(function (seg) {
      var n = Number(latest[seg.key]) || 0;
      return (
        '<span class="dd-an-key"><i class="' + seg.cls + '" aria-hidden="true"></i>' +
        escapeHtml(seg.label) + " " + escapeHtml(String(n)) + "</span>"
      );
    }).join("");
    var pct = a.buy_pct == null ? "—" : fmtEsSmart(a.buy_pct, 1) + "%";
    var trend = a.trend_label
      ? '<p class="dd-ficha-note">' + escapeHtml(a.trend_label) + "</p>"
      : "";
    var target = "";
    var pt = a.price_target;
    if (pt && (pt.mean != null || pt.median != null || pt.low != null || pt.high != null)) {
      var bits = [];
      if (pt.mean != null) bits.push("Objetivo medio USD " + fmtEsNum(pt.mean, 2));
      else if (pt.median != null) bits.push("Objetivo mediano USD " + fmtEsNum(pt.median, 2));
      if (pt.low != null && pt.high != null) {
        bits.push("rango " + fmtEsNum(pt.low, 2) + "–" + fmtEsNum(pt.high, 2));
      }
      target = '<p class="dd-an-target">' + escapeHtml(bits.join(" · ")) + "</p>";
    }
    return (
      head +
      '<p class="dd-ficha-entro">' + escapeHtml(String(total)) + " analistas · " +
      escapeHtml(pct) + " compra · " + escapeHtml(analystPeriod(latest.period)) + "</p>" +
      '<div class="dd-an-bar" role="img" aria-label="Distribución de recomendaciones">' + bar + "</div>" +
      '<div class="dd-an-legend">' + legend + "</div>" +
      trend + target + note + "</section>"
    );
  }

  function fmtIsoFull(iso) {
    var s = String(iso || "");
    if (s.length < 10) return "—";
    return s.slice(8, 10) + "/" + s.slice(5, 7) + "/" + s.slice(0, 4);
  }

  function histSvg(curve) {
    if (!curve || curve.length < 2) return "";
    var w = 640;
    var h = 168;
    var padL = 40;
    var padR = 12;
    var padT = 14;
    var padB = 22;
    var vals = [];
    curve.forEach(function (p) {
      vals.push(Number(p.stocks), Number(p.spy));
      if (p.universe != null) vals.push(Number(p.universe));
    });
    var minV = Math.min.apply(null, vals);
    var maxV = Math.max.apply(null, vals);
    if (!isFinite(minV) || !isFinite(maxV)) return "";
    if (minV === maxV) {
      minV -= 1;
      maxV += 1;
    }
    var span = maxV - minV;
    minV -= span * 0.08;
    maxV += span * 0.08;
    function xAt(i) {
      return padL + (i / (curve.length - 1)) * (w - padL - padR);
    }
    function yAt(v) {
      return padT + (1 - (v - minV) / (maxV - minV)) * (h - padT - padB);
    }
    function path(key) {
      return curve
        .map(function (p, i) {
          return (i ? "L" : "M") + xAt(i).toFixed(1) + " " + yAt(Number(p[key])).toFixed(1);
        })
        .join(" ");
    }
    return (
      '<svg class="dd-hist-svg" viewBox="0 0 ' + w + " " + h +
      '" role="img" aria-label="Curva de sin alertas contra el universo y SPY, base 100">' +
      '<path d="' + path("spy") + '" fill="none" stroke="#A0A0A0" stroke-width="2"/>' +
      (curve[0] && curve[0].universe != null
        ? '<path d="' + path("universe") + '" fill="none" stroke="#5B8DEF" stroke-width="2"/>'
        : "") +
      '<path d="' + path("stocks") + '" fill="none" stroke="#FF8C42" stroke-width="2.4"/>' +
      "</svg>"
    );
  }

  function histCell(stat) {
    if (!stat || !stat.n) {
      return '<p class="dd-hist-empty">Sin ventana cerrada</p>';
    }
    var hit = stat.hit_pct == null ? "—" : fmtEsSmart(stat.hit_pct, 1) + "% en positivo";
    var beat = stat.beat_pct == null ? "—" : fmtEsSmart(stat.beat_pct, 1) + "%";
    var beatU = stat.beat_universe_pct == null ? "" : " · le gana al universo el " + fmtEsSmart(stat.beat_universe_pct, 1) + "%";
    var vsU = stat.excess_universe == null
      ? ""
      : '<p class="dd-hist-vs">exceso vs universo ' + escapeHtml(fmtEsSignedPct(stat.excess_universe, 2)) + "</p>";
    return (
      '<p class="dd-hist-n">' + stat.n + (stat.n === 1 ? " señal" : " señales") + "</p>" +
      '<p class="dd-hist-avg">' + escapeHtml(fmtEsSignedPct(stat.avg, 2)) + "</p>" +
      '<p class="dd-hist-vs">exceso vs SPY ' + escapeHtml(fmtEsSignedPct(stat.excess, 2)) + "</p>" +
      vsU +
      '<p class="dd-hist-hit">' + escapeHtml(hit) + "</p>" +
      '<p class="dd-hist-more">Mediana ' + escapeHtml(fmtEsSignedPct(stat.median, 2)) +
      " · le gana a SPY el " + escapeHtml(beat) + escapeHtml(beatU) +
      " · mejor " + escapeHtml(fmtEsSignedPct(stat.best, 2)) +
      " · peor " + escapeHtml(fmtEsSignedPct(stat.worst, 2)) + "</p>"
    );
  }

  function historialFichaLine(symbol) {
    var block = state.historial;
    if (!block || !symbol) return "";
    var pack = block.by_symbol && block.by_symbol[String(symbol).toUpperCase()];
    var sample = block.sample ? "Muestra. " : "";
    if (!pack || !pack.count) {
      return '<p class="dd-hist-ficha">' + sample + "Sin alertas de riesgo anteriores en el historial.</p>";
    }
    var bits = (pack.signals || []).map(function (item) {
      var ret = item.return_pct == null ? "s/d" : fmtEsSignedPct(item.return_pct, 1);
      var vs = item.excess_pct == null ? "" : " (vs SPY " + fmtEsSignedPct(item.excess_pct, 1);
      if (item.excess_universe_pct != null) {
        vs += (vs ? ", " : " (") + "vs universo " + fmtEsSignedPct(item.excess_universe_pct, 1);
      }
      if (vs) vs += ")";
      var status = item.status === "cerrada" ? "cerrada" : "en curso";
      return fmtDayMonth(item.date) + " " + ret + vs + ", " + status;
    });
    var extra = pack.count > (pack.signals || []).length ? " Hay " + pack.count + " en total." : "";
    return '<p class="dd-hist-ficha">' + sample + "Sin alertas: " + escapeHtml(bits.join(" · ")) + "." + escapeHtml(extra) + "</p>";
  }

  function histGroups(source, groupLabels) {
    var horizons = (source && source.horizons) || [5, 10, 20];
    return groupLabels
      .map(function (pair) {
        var id = pair[0];
        var cols = horizons
          .map(function (h) {
            var stat = source.table && source.table[id] && source.table[id][String(h)];
            var meta = source.horizons_meta && source.horizons_meta[String(h)];
            var badge = "";
            if (meta && meta.provisional) {
              badge = '<p class="dd-hist-prov">' + escapeHtml(meta.label || "Provisorio (reconstruido)") + "</p>";
              if (id === "verde" && meta.note) {
                badge += '<p class="dd-hist-prov-note">' + escapeHtml(meta.note) + "</p>";
              }
            }
            return (
              '<div class="dd-hist-h"><p class="dd-kpi-label">' + h + " ruedas</p>" +
              badge + histCell(stat) + "</div>"
            );
          })
          .join("");
        return (
          '<article class="dd-hist-group" data-group="' + id + '">' +
          '<h3><span class="dd-hist-dot" aria-hidden="true"></span>' + pair[1] + "</h3>" +
          '<div class="dd-hist-horizons">' + cols + "</div></article>"
        );
      })
      .join("");
  }

  function histEquity(equity, stockLabel) {
    if (!equity || equity.stocks_return_pct == null) return "";
    var uni = equity.universe_return_pct == null
      ? ""
      : " · universo: " + escapeHtml(fmtEsSignedPct(equity.universe_return_pct, 2));
    var hasUni = equity.curve && equity.curve.length && equity.curve[0].universe != null;
    return (
      '<p class="dd-hist-sentence">' + escapeHtml(stockLabel) + ": " +
      escapeHtml(fmtEsSignedPct(equity.stocks_return_pct, 2)) +
      " · con ETF: " + escapeHtml(fmtEsSignedPct(equity.all_return_pct, 2)) +
      uni +
      " · SPY: " + escapeHtml(fmtEsSignedPct(equity.spy_return_pct, 2)) + ".</p>" +
      histSvg(equity.curve) +
      '<p class="dd-hist-legend"><span><i class="is-stocks"></i>' + escapeHtml(stockLabel) + "</span>" +
      (hasUni ? '<span><i class="is-universe"></i>Universo</span>' : "") +
      '<span><i class="is-spy"></i>SPY</span></p>' +
      '<p class="dd-hist-equity-note">' + escapeHtml(equity.note || "") + "</p>"
    );
  }

  function renderHistorial(block) {
    var root = document.getElementById("hist-root");
    if (!root) return;
    if (!block || !block.table) {
      root.innerHTML = '<p class="dd-empty">Sin historial en esta publicación. Se arma al correr build.py.</p>';
      return;
    }
    var groups = histGroups(block, [
      ["verde", "Sin alertas"],
      ["ambar", "Ámbar"],
      ["rojo", "Alerta"],
      ["universo", "Universo"],
    ]);
    var real = block.real_days || 0;
    var recon = block.reconstructed_days || 0;
    var horizons = block.horizons || [5, 10, 20];
    var anyProv = horizons.some(function (h) {
      var meta = block.horizons_meta && block.horizons_meta[String(h)];
      return meta && meta.provisional;
    });
    var latest = "";
    if (block.latest && block.latest.date) {
      latest =
        " Última foto: " + fmtIsoFull(block.latest.date) + ", " +
        (block.latest.after_close ? "después del cierre." : "con la rueda todavía abierta.");
    }
    var daysLine = real + (real === 1 ? " rueda real." : " ruedas reales.");
    if (anyProv && recon) {
      var purgeAt = block.purge_real_days || 60;
      daysLine += " Reconstrucción provisoria: " + recon + " ruedas. Se borra al llegar a " + purgeAt + " ruedas reales.";
    }
    var sample = block.sample
      ? '<p class="dd-hist-sample">Muestra de ejemplo para la vista. No son precios reales.</p>'
      : "";
    var recent = (block.recent || [])
      .map(function (item) {
        var ret = item.return_pct == null ? "s/d" : fmtEsSignedPct(item.return_pct, 1);
        var vs = item.excess_pct == null ? "vs SPY —" : "vs SPY " + fmtEsSignedPct(item.excess_pct, 1);
        if (item.excess_universe_pct != null) vs += " · vs universo " + fmtEsSignedPct(item.excess_universe_pct, 1);
        var status = item.status === "cerrada" ? "cerrada" : "en curso";
        return (
          '<a class="dd-hist-signal" href="#/t/' + encodeURIComponent(item.symbol) + '">' +
          "<span>" + escapeHtml(fmtIsoFull(item.date)) + "</span>" +
          '<span class="dd-hist-sym">' + escapeHtml(item.symbol) + "</span>" +
          '<span class="dd-hist-ret">' + escapeHtml(ret + " · " + vs) + "</span>" +
          "<span>" + escapeHtml(status) + "</span></a>"
        );
      })
      .join("");
    var eqText = histEquity(block.equity, "Sin alertas");
    var legacy = block.legacy;
    var legacyHtml = "";
    if (legacy && legacy.table) {
      legacyHtml =
        '<section class="dd-hist-legacy">' +
        "<h3>" + escapeHtml(legacy.label || "Definición anterior") + "</h3>" +
        '<p class="dd-hist-legacy-note">' + escapeHtml(legacy.note || block.definition_note || "") + "</p>" +
        '<p class="dd-hist-sentence">' + escapeHtml(legacy.sentence || "") + "</p>" +
        '<div class="dd-hist-groups">' + histGroups(legacy, [
          ["verde", "Verde (entrada)"],
          ["ambar", "Ámbar"],
          ["rojo", "Rojo"],
          ["universo", "Universo"],
        ]) + "</div>" +
        histEquity(legacy.equity, "Verdes (entrada)") +
        "</section>";
    }
    var fine = document.getElementById("hist-disclaimer");
    if (fine) {
      var legal = block.disclaimer || "El verde es «sin alertas de riesgo», no una compra. Resultados pasados no garantizan resultados futuros.";
      if (anyProv && block.earnings_note) legal += " " + block.earnings_note;
      fine.textContent = legal;
    }
    var helpParts = [];
    if (!legacy && block.definition_note) {
      helpParts.push('<p class="dd-hist-def">' + escapeHtml(block.definition_note) + "</p>");
    }
    if (block.dedup) helpParts.push('<p class="dd-hist-rule">' + escapeHtml(block.dedup) + "</p>");
    if (block.universe_benchmark) helpParts.push('<p class="dd-hist-rule">' + escapeHtml(block.universe_benchmark) + "</p>");
    var help = helpParts.length
      ? '<details class="dd-help"><summary><span class="dd-help-i" aria-hidden="true">ⓘ</span> Cómo se arma</summary>' +
        helpParts.join("") + "</details>"
      : "";
    root.innerHTML =
      sample +
      '<p class="dd-hist-meta">' + daysLine + escapeHtml(latest) + "</p>" +
      '<p class="dd-hist-sentence">' + escapeHtml(block.sentence || "") + "</p>" +
      (block.todos_los_dias_sentence ? '<p class="dd-hist-alt">' + escapeHtml(block.todos_los_dias_sentence) + "</p>" : "") +
      help +
      '<div class="dd-hist-groups">' + groups + "</div>" +
      (recent ? '<div class="dd-hist-list">' + recent + "</div>" : '<p class="dd-empty">Sin señales reales de esta definición.</p>') +
      eqText +
      legacyHtml;
  }

  var LIVE_BANNER = "En vivo · provisorio hasta el cierre · precios con ~15 min de demora";

  function sessionDay(data) {
    var rows = (data && data.ranking) || [];
    var raw = "";
    for (var i = 0; i < rows.length; i++) {
      if (rows[i] && String(rows[i].symbol || "").toUpperCase() === "SPY" && rows[i].asof) {
        raw = String(rows[i].asof);
        break;
      }
    }
    if (!raw && data && data.generated_at) raw = String(data.generated_at);
    var match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return "";
    return match[3] + "/" + match[2];
  }

  function sessionBannerText(data) {
    if (!data) return "";
    if (data.sesion_aviso) return String(data.sesion_aviso);
    var mode = String(data.sesion || data.session || "");
    if (mode === "intradia" || mode === "intraday") return LIVE_BANNER;
    if (mode === "cierre" || mode === "close") {
      var day = sessionDay(data);
      return day ? "Cierre del " + day : "Cierre";
    }
    return "";
  }

  function renderSessionBanner(data) {
    var el = document.getElementById("session-banner");
    if (!el) return;
    var text = sessionBannerText(data);
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      el.classList.remove("is-live");
      return;
    }
    el.hidden = false;
    el.textContent = text;
    var mode = String((data && (data.sesion || data.session)) || "");
    var live = mode === "intradia" || mode === "intraday" || text.indexOf("En vivo") === 0;
    el.classList.toggle("is-live", live);
  }

  function renderSampleNotice(data) {
    var el = document.getElementById("sample-notice");
    if (!el) return;
    var msg = data && data.sample_notice;
    if (msg) {
      el.hidden = false;
      el.textContent = msg;
    } else {
      el.hidden = true;
      el.textContent = "";
    }
  }

  var REGIME_COLORS = {
    red: "#F87171",
    orange: "#FF8C42",
    yellow: "#FBBF24",
    green: "#34D399",
  };

  function fmtPts(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var x = Math.round(Number(n) * 10) / 10;
    if (Math.abs(x - Math.round(x)) < 0.05) return String(Math.round(x));
    return x.toFixed(1);
  }

  function regimePtsClass(points, max) {
    if (points == null || max == null || Number(max) <= 0) return "is-muted";
    if (Number(points) <= 0) return "is-red";
    if (Number(points) >= Number(max) - 0.05) return "is-green";
    return "is-orange";
  }

  function regimeIcon(id) {
    if (id === "indices") {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16l5-5 3.2 3.2L20 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M14.5 6H20v5.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    }
    if (id === "breadth") {
      return '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.7"/><ellipse cx="12" cy="12" rx="3.6" ry="8" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M4 12h16M6.2 8.2h11.6M6.2 15.8h11.6" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4.2a3.1 3.1 0 0 1 3 2.4 2.7 2.7 0 0 1 2.3 3.2 2.8 2.8 0 0 1-.4 4.6A3 3 0 0 1 12 19.2a3 3 0 0 1-4.9-4.8 2.8 2.8 0 0 1-.4-4.6 2.7 2.7 0 0 1 2.3-3.2A3.1 3.1 0 0 1 12 4.2z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M12 8.2v7.2M9.4 11.2c.7.8 1.6 1.1 2.6 1.1s1.9-.3 2.6-1.1" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
  }

  function regimeGaugeSvg(score, color) {
    var r = 74;
    var cx = 100;
    var cy = 96;
    var startX = cx - r;
    var endX = cx + r;
    var len = Math.PI * r;
    var pct = Math.max(0, Math.min(100, Number(score) || 0)) / 100;
    var dash = (len * pct).toFixed(2);
    var label = score == null ? "Sin puntaje" : "Puntaje " + score + " de 100";
    return (
      '<svg class="dd-regime-gauge" viewBox="0 0 200 112" role="img" aria-label="' + escapeHtml(label) + '">' +
      '<path d="M ' + startX + " " + cy + " A " + r + " " + r + " 0 0 1 " + endX + " " + cy + '" fill="none" stroke="rgba(255,255,255,0.1)" stroke-width="14" stroke-linecap="round"/>' +
      '<path d="M ' + startX + " " + cy + " A " + r + " " + r + " 0 0 1 " + endX + " " + cy + '" fill="none" stroke="' + color + '" stroke-width="14" stroke-linecap="round" stroke-dasharray="' + dash + " " + len.toFixed(2) + '"/>' +
      "</svg>"
    );
  }

  function regimeChartSvg(series) {
    var pts = (series || []).filter(function (p) {
      return p && p.pct != null && !isNaN(Number(p.pct));
    });
    if (pts.length < 2) {
      return '<p class="dd-regime-chart-empty">Sin suficientes ruedas para la serie.</p>';
    }
    var vals = pts.map(function (p) { return Number(p.pct); });
    var vmin = Math.min.apply(null, vals);
    var vmax = Math.max.apply(null, vals);
    var pad = Math.max(4, (vmax - vmin) * 0.18);
    var lo = Math.max(0, vmin - pad);
    var hi = Math.min(100, vmax + pad);
    if (hi - lo < 10) {
      var mid = (vmin + vmax) / 2;
      lo = Math.max(0, mid - 6);
      hi = Math.min(100, mid + 6);
    }
    if (hi <= lo) hi = lo + 1;
    var W = 640;
    var H = 214;
    var L = 46;
    var R = 10;
    var T = 12;
    var B = 28;
    var iw = W - L - R;
    var ih = H - T - B;
    function xAt(i) {
      return L + (pts.length === 1 ? iw / 2 : (i / (pts.length - 1)) * iw);
    }
    function yAt(v) {
      return T + (1 - (v - lo) / (hi - lo)) * ih;
    }
    var line = pts.map(function (p, i) {
      return (i ? "L" : "M") + xAt(i).toFixed(1) + " " + yAt(Number(p.pct)).toFixed(1);
    }).join(" ");
    var base = (T + ih).toFixed(1);
    var area = line + " L" + xAt(pts.length - 1).toFixed(1) + " " + base + " L" + xAt(0).toFixed(1) + " " + base + " Z";
    var grid = "";
    var yLabels = "";
    var rawStep = (hi - lo) / 4;
    var mag = Math.pow(10, Math.floor(Math.log10(Math.max(rawStep, 0.1))));
    var err = rawStep / mag;
    var nice = err < 1.5 ? 1 : err < 3.5 ? 2 : err < 7.5 ? 5 : 10;
    var step = nice * mag;
    var start = Math.ceil(lo / step) * step;
    var guard = 0;
    for (var val = start; val <= hi + step * 0.01 && guard < 8; val += step, guard++) {
      if (val < lo - 0.01) continue;
      var yy = yAt(val);
      grid += '<line x1="' + L + '" y1="' + yy.toFixed(1) + '" x2="' + (W - R) + '" y2="' + yy.toFixed(1) + '" stroke="rgba(255,255,255,0.07)"/>';
      yLabels += '<text x="' + (L - 8) + '" y="' + (yy + 4).toFixed(1) + '" text-anchor="end" fill="#8d8d8d" font-size="12" font-family="Plus Jakarta Sans, Inter, sans-serif">' + Math.round(val) + "%</text>";
    }
    var xLabels = "";
    var want = Math.min(7, pts.length);
    var seen = {};
    var steps = Math.max(want - 1, 1);
    for (var k = 0; k < want; k++) {
      var idx = Math.round((k * (pts.length - 1)) / steps);
      if (seen[idx]) continue;
      seen[idx] = true;
      var ds = String(pts[idx].date || "");
      var lab = ds.length >= 10 ? ds.slice(5) : ds;
      var anchor = "middle";
      if (idx === 0) anchor = "start";
      if (idx === pts.length - 1) anchor = "end";
      xLabels += '<text x="' + xAt(idx).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="' + anchor + '" fill="#8d8d8d" font-size="12" font-family="Plus Jakarta Sans, Inter, sans-serif">' + escapeHtml(lab) + "</text>";
    }
    return (
      '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Porcentaje de activos sobre la EMA200 en las últimas ruedas">' +
      "<defs><linearGradient id=\"ddRegimeFill\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">" +
      '<stop offset="0%" stop-color="#34D399" stop-opacity="0.38"/>' +
      '<stop offset="100%" stop-color="#34D399" stop-opacity="0.02"/>' +
      "</linearGradient></defs>" +
      grid +
      '<path d="' + area + '" fill="url(#ddRegimeFill)"/>' +
      '<path d="' + line + '" fill="none" stroke="#34D399" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>' +
      yLabels + xLabels +
      "</svg>"
    );
  }

  function renderMarketRegime(data) {
    var root = document.getElementById("market-regime");
    var body = document.getElementById("market-regime-body");
    if (!root || !body) return;
    var block = data && data.market_regime;
    if (!block || block.score == null && !(block.components || []).length) {
      root.hidden = true;
      body.innerHTML = "";
      return;
    }
    var band = block.band || {};
    var colorName = band.color || "orange";
    var color = REGIME_COLORS[colorName] || REGIME_COLORS.orange;
    root.hidden = false;
    root.setAttribute("data-band", colorName);
    root.style.setProperty("--regime-color", color);

    var scoreText = block.score == null ? "—" : String(block.score);
    var components = block.components || [];
    var rows = components.map(function (comp) {
      var pts;
      if (!comp.available) {
        pts = '<span class="dd-regime-pts is-muted">sin dato</span>';
      } else {
        pts = '<span class="dd-regime-pts ' + regimePtsClass(comp.points, comp.max_points) + '">' +
          fmtPts(comp.points) + "/" + fmtPts(comp.max_points) + " pts</span>";
      }
      var sub = comp.detail ? '<span class="dd-regime-row-sub">' + escapeHtml(comp.detail) + "</span>" : "";
      return (
        '<div class="dd-regime-row">' +
        '<span class="dd-regime-ico">' + regimeIcon(comp.id) + "</span>" +
        '<span class="dd-regime-row-label">' + escapeHtml(comp.label || "") + sub + "</span>" +
        pts +
        "</div>"
      );
    }).join("");

    var hl = block.highs_lows || {};
    var highs = hl.highs != null ? hl.highs : "—";
    var lows = hl.lows != null ? hl.lows : "—";
    var line = band.line || "—";
    var disclaimer = block.disclaimer || band.disclaimer || "Guía automática de exposición, no es un consejo de inversión.";
    var footer = block.footer || "";

    body.innerHTML =
      '<div class="dd-regime-hero">' +
      '<div class="dd-regime-gauge-wrap">' +
      regimeGaugeSvg(block.score, color) +
      '<div class="dd-regime-score">' +
      '<span class="dd-regime-score-num" style="color:' + color + '">' + escapeHtml(scoreText) + "</span>" +
      '<span class="dd-regime-score-of">de 100</span>' +
      "</div></div>" +
      '<div class="dd-regime-exposure">' +
      '<p class="dd-regime-kicker">Exposición sugerida</p>' +
      '<p class="dd-regime-exposure-line">' + escapeHtml(line) + "</p>" +
      '<p class="dd-regime-disclaimer">' + escapeHtml(disclaimer) + "</p>" +
      "</div></div>" +
      '<details class="dd-help">' +
      '<summary><span class="dd-help-i" aria-hidden="true">ⓘ</span> Ver el medidor</summary>' +
      rows +
      '<div class="dd-regime-hl">' +
      '<span class="dd-regime-hoy">HOY</span>' +
      "<span>Nuevos máximos / mínimos de 52 semanas hoy: " +
      '<span class="dd-regime-hl-high">' + escapeHtml(String(highs)) + "</span>" +
      " / " +
      '<span class="dd-regime-hl-low">' + escapeHtml(String(lows)) + "</span>" +
      "</span></div>" +
      '<p class="dd-regime-chart-title">% de activos sobre su EMA200 – últimos ~2 meses</p>' +
      '<div class="dd-regime-chart">' + regimeChartSvg(block.breadth_series) + "</div>" +
      (footer ? '<p class="dd-regime-foot">' + escapeHtml(footer) + "</p>" : "") +
      "</details>";
  }

  function syncClamp(textId, btnId) {
    var el = document.getElementById(textId);
    var btn = document.getElementById(btnId);
    if (!el || !btn) return;
    window.requestAnimationFrame(function () {
      if (el.classList.contains("is-open")) {
        btn.hidden = false;
        btn.textContent = "Ver menos";
        return;
      }
      btn.hidden = el.scrollHeight <= el.clientHeight + 1;
      btn.textContent = "Ver más";
    });
  }

  function artTodayIso() {
    try {
      return new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Argentina/Buenos_Aires",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(new Date());
    } catch (e) {
      return "";
    }
  }

  function renderToday(data) {
    var rows = (data && data.ranking) || [];
    var stocks = 0;
    var etfs = 0;
    rows.forEach(function (r) {
      if (!r.entry || r.entry.verdict !== "verde") return;
      if (String(r.kind || "").toLowerCase() === "etf") etfs += 1;
      else stocks += 1;
    });
    setText("today-clear", String(stocks));
    var sub = stocks === 1 ? "acción" : "acciones";
    if (etfs) sub += " · " + etfs + " ETF";
    setText("today-clear-sub", sub);

    var today = artTodayIso();
    var upcoming = ((data && data.earnings) || []).filter(function (e) {
      return today && String(e.date || "") >= today;
    });
    setText("today-earn", String(upcoming.length));
    if (!upcoming.length) {
      setText("today-earn-sub", "Nada pendiente esta semana");
      return;
    }
    setText(
      "today-earn-sub",
      upcoming
        .map(function (e) {
          var when = String(e.date) === today ? "hoy" : fmtDayMonth(e.date);
          var hour = hourLabel(e.hour);
          return (e.symbol || "—") + " " + when + (hour ? ", " + hour : "");
        })
        .join(" · ")
    );
  }

  var FORMULA_LABELS = {
    desk_score: "Desk Score",
    rs_score: "RS Score",
    tendencia: "Tendencia",
    fuerza_rs: "Fuerza RS",
    contraccion: "Contracción",
    vol_rel_20d: "Volumen relativo",
    dist_ema200_pct: "Distancia a la EMA200",
    regime: "Régimen del universo",
    market_regime: "Régimen de mercado",
    top10_return: "Retorno Top 10",
    top10_entry: "Entró al Top 10",
    top10_walkforward: "Simulación walk-forward",
    pillar_points: "Puntos de cada pilar",
    range_52w: "Rango de 52 semanas",
    change_pct: "Cambio del día",
    trend_gate: "Gate de tendencia",
    rs_weekly: "RS semanal",
    sectors: "Sectores",
    patterns: "Patrones",
    signals: "Señales",
    rrg: "Rotación (RRG)",
    insiders: "Insiders",
    fundamentals: "Salud de la empresa",
    resumen: "Resumen del día",
    historial_semaforo: "Historial del semáforo",
    entry: "Semáforo",
    analysts: "Analistas",
  };

  function renderFormulas(formulas) {
    var root = document.getElementById("formula-list");
    if (!root) return;
    var keys = formulas && typeof formulas === "object" ? Object.keys(formulas) : [];
    if (!keys.length) {
      root.innerHTML = '<p class="dd-empty">Sin fórmulas en esta publicación.</p>';
      return;
    }
    root.innerHTML = keys
      .map(function (key) {
        var val = formulas[key];
        var text = val == null ? "—" : typeof val === "string" ? val : JSON.stringify(val);
        return (
          "<div><dt>" + escapeHtml(FORMULA_LABELS[key] || key) + "</dt><dd>" +
          escapeHtml(text) + "</dd></div>"
        );
      })
      .join("");
  }

  function renderAnalysts() {
    var root = document.getElementById("analyst-list");
    if (!root) return;
    var rows = (state.ranking || []).filter(function (r) {
      return String(r.kind || "").toLowerCase() !== "etf" && r.analysts && r.analysts.buy_pct != null;
    });
    rows.sort(function (a, b) {
      return Number(b.analysts.buy_pct) - Number(a.analysts.buy_pct);
    });
    if (!rows.length) {
      root.innerHTML = '<p class="dd-empty">Sin recomendaciones de analistas en esta publicación.</p>';
      return;
    }
    root.innerHTML = rows
      .map(function (r) {
        var a = r.analysts;
        var bits = [fmtEsSmart(a.buy_pct, 1) + "% compra"];
        var total = (a.latest && a.latest.total) || a.total;
        if (total) bits.push(total + (Number(total) === 1 ? " analista" : " analistas"));
        if (a.trend_label) bits.push(a.trend_label);
        var pt = a.price_target;
        if (pt && pt.mean != null) bits.push("objetivo USD " + fmtEsNum(pt.mean, 2));
        else if (pt && pt.median != null) bits.push("objetivo USD " + fmtEsNum(pt.median, 2));
        if (pt && pt.low != null && pt.high != null) {
          bits.push("rango " + fmtEsNum(pt.low, 2) + "–" + fmtEsNum(pt.high, 2));
        }
        return linkRow(r, bits.join(" · "));
      })
      .join("");
  }

  function fmtSignedPoints(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Math.round(Number(n) * 10) / 10;
    var body = fmtNum(Math.abs(v), Math.abs(v - Math.round(v)) < 0.05 ? 0 : 1);
    if (v > 0) return "+" + body;
    if (v < 0) return "−" + body;
    return body;
  }

  function renderRsBoard() {
    var body = document.getElementById("rs-body");
    var def = document.getElementById("rs-definition");
    if (def) def.textContent = (state.rsWeekly && state.rsWeekly.definition) || RS_CAPTION_FALLBACK;
    if (!body) return;
    var rows = (state.ranking || []).filter(function (r) {
      return r.rs_weekly && r.rs_weekly.length;
    });
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="5" class="dd-empty">Sin serie semanal. Se calcula al correr build.py.</td></tr>';
      return;
    }
    rows.sort(function (a, b) {
      return Number(b.rs_score || 0) - Number(a.rs_score || 0);
    });
    body.innerHTML = rows
      .map(function (r) {
        var series = r.rs_weekly || [];
        var now = series[series.length - 1];
        var ago = series.length > 4 ? series[series.length - 5] : null;
        var delta = now != null && ago != null ? Number(now) - Number(ago) : null;
        return (
          '<tr data-symbol="' + escapeHtml(r.symbol) + '" tabindex="0" role="link" aria-label="Ver ficha de ' +
          escapeHtml(r.symbol) + '"><td>' + tickerWithLogo(r, "dd-ticker") + "</td><td>" +
          escapeHtml(now == null ? "—" : fmtNum(now, 1)) + "</td><td>" +
          escapeHtml(ago == null ? "—" : fmtNum(ago, 1)) + '</td><td class="' + distClass(delta) + '">' +
          escapeHtml(fmtSignedPoints(delta)) + "</td><td>" + sparklineSvg(series) + "</td></tr>"
        );
      })
      .join("");
  }

  function fmtUsdCompact(n) {
    if (n == null || Number.isNaN(Number(n))) return "";
    var v = Number(n);
    var sign = v < 0 ? "−" : "";
    var a = Math.abs(v);
    if (a >= 1e9) return sign + "USD " + fmtEsSmart(a / 1e9, 1) + " mil millones";
    return fmtUsdShort(v);
  }

  function applyData(data) {
    state.ranking = data.ranking || [];
    state.historial = data.historial_semaforo || null;
    state.logos = data.logos || {};
    state.earnings = data.earnings || [];
    state.rsWeekly = data.rs_weekly || null;
    state.ready = true;
    state.loadError = "";
    renderKpis(data);
    renderMarketRegime(data);
    renderResumen(data);
    renderToday(data);
    renderTop10(data.top10_return);
    renderWalkforward(data.top10_walkforward);
    renderHistorial(data.historial_semaforo);
    renderEarnings(data.earnings);
    renderSectors(data.sectors);
    renderInsiders(data.insider_buys);
    renderPatterns(data.patterns);
    applyFilters();
    renderNotes(data.notes);
    renderAnalysts();
    renderRsBoard();
    renderFormulas(data.formulas);
    renderPodium();
    renderSignals(data.signals);
    renderRrg(data.rrg);
    renderSampleNotice(data);
    renderSessionBanner(data);
    state.baseTitle = "Angus — " + ((data.kpis && data.kpis.activos) || "?") + " activos";
    document.title = state.baseTitle;
    renderRoute();
  }

  function loadData(opts) {
    opts = opts || {};
    if (state.loading) return Promise.resolve();
    setLoading(true);
    var url = "datos.json?ts=" + Date.now();
    return fetch(url, { cache: "no-store" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        applyData(data);
        markUiRefreshOk();
        var st = document.getElementById("refresh-status");
        if (st) st.textContent = "Auto cada 5 min";
      })
      .catch(function (err) {
        if (opts.silent) {
          var st = document.getElementById("refresh-status");
          if (st) st.textContent = "Error al refrescar";
        } else {
          fail("No se pudo cargar datos.json (" + err.message + "). Ejecutá python3 build.py");
        }
      })
      .finally(function () {
        setLoading(false);
      });
  }

  function clearAuto() {
    if (state.autoTimer) {
      clearInterval(state.autoTimer);
      state.autoTimer = null;
    }
  }

  function startAuto() {
    clearAuto();
    if (document.hidden) return;
    state.autoTimer = setInterval(function () {
      if (!document.hidden) loadData({ silent: true });
    }, AUTO_MS);
  }

  function bindFilters() {
    var kindGroup = document.querySelector('.dd-filter-group[data-filter="kind"]');
    if (kindGroup) {
      kindGroup.addEventListener("click", function (ev) {
        var btn = ev.target.closest(".dd-chip");
        if (!btn || !kindGroup.contains(btn)) return;
        kindGroup.querySelectorAll(".dd-chip").forEach(function (b) {
          b.classList.remove("is-active");
        });
        btn.classList.add("is-active");
        state.kind = btn.getAttribute("data-kind") || "";
        applyFilters();
      });
    }

    document.querySelectorAll(".dd-chip-toggle").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var flag = btn.getAttribute("data-flag");
        if (!flag || !(flag in state.flags)) return;
        state.flags[flag] = !state.flags[flag];
        btn.classList.toggle("is-active", state.flags[flag]);
        btn.setAttribute("aria-pressed", state.flags[flag] ? "true" : "false");
        applyFilters();
      });
    });

    var search = document.getElementById("filter-search");
    if (search) {
      search.addEventListener("input", function () {
        state.search = search.value || "";
        applyFilters();
      });
    }

    var sectorGroup = document.querySelector('.dd-filter-group[data-filter="sector"]');
    if (sectorGroup) {
      sectorGroup.addEventListener("click", function (ev) {
        var btn = ev.target.closest(".dd-chip");
        if (!btn || !sectorGroup.contains(btn)) return;
        var key = btn.getAttribute("data-sector") || "";
        if (!key) {
          state.sector = "";
          state.sectorLabel = "";
          syncSectorActive();
          applyFilters();
          return;
        }
        setSectorFilter(key, true);
      });
    }

    var sectorGrid = document.getElementById("sector-grid");
    if (sectorGrid) {
      sectorGrid.addEventListener("click", function (ev) {
        if (ev.target.closest("a")) return;
        var card = ev.target.closest(".dd-sector-card");
        if (!card || !sectorGrid.contains(card)) return;
        setSectorFilter(card.getAttribute("data-sector") || "", true);
      });
    }
  }

  function bindRefresh() {
    var btn = document.getElementById("btn-refresh");
    if (btn) {
      btn.addEventListener("click", function () {
        loadData({ silent: true });
      });
    }
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) {
        clearAuto();
      } else {
        loadData({ silent: true });
        startAuto();
      }
    });
  }

  function fmtEsNum(n, digits) {
    var v = Number(n);
    if (Number.isNaN(v)) return "—";
    var neg = v < 0;
    var fixed = Math.abs(v).toFixed(digits);
    var parts = fixed.split(".");
    var intp = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    var s = digits > 0 ? intp + "," + parts[1] : intp;
    return (neg ? "−" : "") + s;
  }

  function fmtEsSmart(n, maxDigits) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Number(n);
    var digits = Math.abs(v - Math.round(v)) < 0.001 ? 0 : maxDigits;
    return fmtEsNum(v, digits);
  }

  function fmtPrice(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Number(n);
    var digits = Math.abs(v - Math.round(v)) < 0.001 ? 0 : 2;
    return "$" + fmtEsNum(v, digits);
  }

  function fmtEsSignedPct(n, digits) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    var v = Number(n);
    var d = digits == null ? 2 : digits;
    var body = fmtEsNum(Math.abs(v), d);
    if (v > 0) return "+" + body + "%";
    if (v < 0) return "−" + body + "%";
    return body + "%";
  }

  function fmtDayMonth(iso) {
    var s = String(iso || "");
    if (s.length < 10) return s;
    return s.slice(8, 10) + "/" + s.slice(5, 7);
  }

  function parseTickerHash() {
    var raw = (location.hash || "").replace(/^#/, "");
    var h = raw;
    try {
      h = decodeURIComponent(raw);
    } catch (e) {
      h = raw;
    }
    var m = /^\/t\/([A-Za-z0-9._-]+)$/.exec(h);
    return m ? m[1].toUpperCase() : null;
  }

  function rowBySymbol(sym) {
    var want = String(sym || "").toUpperCase();
    for (var i = 0; i < state.ranking.length; i++) {
      if (String(state.ranking[i].symbol || "").toUpperCase() === want) return state.ranking[i];
    }
    return null;
  }

  function pillarRows(row) {
    var src = row.pillar_points || {};
    var raw = row.pillars || {};
    return PILLAR_SPEC.map(function (spec) {
      var item = src[spec.key] || {};
      var max = item.max != null ? Number(item.max) : spec.max;
      var points = item.points != null ? Number(item.points) : null;
      if ((points == null || Number.isNaN(points)) && raw[spec.key] != null) {
        points = Math.round(Number(raw[spec.key]) * (max / 100) * 10) / 10;
      }
      if (points != null && Number.isNaN(points)) points = null;
      return { key: spec.key, label: spec.label, points: points, max: max };
    });
  }

  function earningsFor(sym) {
    var want = String(sym || "").toUpperCase();
    var list = (state.earnings || []).filter(function (e) {
      return String(e.symbol || "").toUpperCase() === want;
    });
    if (!list.length) return null;
    list.sort(function (a, b) {
      return String(a.date || "").localeCompare(String(b.date || ""));
    });
    var now = new Date();
    var iso =
      now.getFullYear() +
      "-" +
      String(now.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(now.getDate()).padStart(2, "0");
    var upcoming = list.filter(function (e) {
      return String(e.date || "") >= iso;
    });
    var pick = upcoming[0] || list[list.length - 1];
    return { row: pick, upcoming: String(pick.date || "") >= iso };
  }

  function gateText(row) {
    if (row.trend_gate) return row.trend_gate;
    if (row.ema200 == null && row.dist_ema200_pct == null) return "Sin EMA200";
    var price = row.above_ema200 ? "Precio > EMA200" : "Precio < EMA200";
    if (row.ema200_slope_up == null) return price;
    return price + (row.ema200_slope_up ? " con pendiente +" : " con pendiente -");
  }

  function gateMark(row) {
    var text = gateText(row);
    if (text === "Sin EMA200") return { cls: "is-warn", ch: "–" };
    if (row.above_ema200 && row.ema200_slope_up === true) return { cls: "is-ok", ch: "✓" };
    if (row.above_ema200) return { cls: "is-warn", ch: "–" };
    return { cls: "is-bad", ch: "!" };
  }

  function gaugeHtml(score) {
    var r = 46;
    var circ = 2 * Math.PI * r;
    var pct = score == null || Number.isNaN(Number(score)) ? 0 : Math.max(0, Math.min(100, Number(score)));
    var dash = (pct / 100) * circ;
    var label = score == null || Number.isNaN(Number(score)) ? "—" : fmtEsSmart(score, 1);
    return (
      '<div class="dd-gauge">' +
      '<svg viewBox="0 0 120 120" aria-hidden="true">' +
      '<circle class="dd-gauge-track" cx="60" cy="60" r="' + r + '" />' +
      '<circle class="dd-gauge-value-ring" cx="60" cy="60" r="' + r + '" stroke-dasharray="' +
      dash.toFixed(2) + " " + circ.toFixed(2) + '" />' +
      "</svg>" +
      '<div class="dd-gauge-num">' + escapeHtml(label) + "</div>" +
      "</div>"
    );
  }

  function pillarsHtml(row) {
    return pillarRows(row)
      .map(function (p) {
        var width = 0;
        if (p.points != null && p.max) width = Math.max(0, Math.min(100, (p.points / p.max) * 100));
        var pts =
          p.points == null ? "—" : fmtEsSmart(p.points, 1) + "/" + fmtEsSmart(p.max, 1);
        return (
          '<div class="dd-pillar">' +
          '<span class="dd-pillar-name">' + escapeHtml(p.label) + "</span>" +
          '<span class="dd-pillar-track"><span class="dd-pillar-fill" data-pillar="' +
          escapeHtml(p.key) +
          '" style="width:' + width.toFixed(1) + '%"></span></span>' +
          '<span class="dd-pillar-pts">' + escapeHtml(pts) + "</span>" +
          "</div>"
        );
      })
      .join("");
  }

  function penaltyFootnote(flags) {
    var bits = (flags || []).filter(function (f) {
      return SCORE_PENALTY[f];
    });
    if (!bits.length) return "";
    var text = bits
      .map(function (f) {
        return (FLAG_LABELS[f] || f) + " −" + SCORE_PENALTY[f];
      })
      .join(", ");
    return (
      '<p class="dd-ficha-note">El Desk Score resta estas penalizaciones después de sumar los pilares: ' +
      escapeHtml(text) +
      ".</p>"
    );
  }

  function rsChartSvg(values, dates) {
    var nums = (values || []).map(function (v) {
      if (v == null || v === "") return null;
      var n = Number(v);
      return Number.isNaN(n) ? null : n;
    });
    var valid = nums.filter(function (v) {
      return v != null;
    });
    if (valid.length < 2) {
      return '<p class="dd-ficha-empty">Sin serie semanal todavía. Se calcula al correr build.py.</p>';
    }
    var w = 360;
    var h = 168;
    var padL = 32;
    var padR = 12;
    var padT = 16;
    var padB = 26;
    var innerW = w - padL - padR;
    var innerH = h - padT - padB;
    function xAt(i) {
      if (nums.length <= 1) return padL;
      return padL + (i / (nums.length - 1)) * innerW;
    }
    function yAt(v) {
      var c = Math.max(0, Math.min(100, v));
      return padT + (1 - c / 100) * innerH;
    }
    var segments = [];
    var cur = [];
    nums.forEach(function (v, i) {
      if (v == null) {
        if (cur.length) segments.push(cur);
        cur = [];
      } else {
        cur.push(i);
      }
    });
    if (cur.length) segments.push(cur);
    var up = valid[valid.length - 1] >= valid[0];
    var stroke = up ? "#34D399" : "#F87171";
    var paths = segments
      .map(function (seg) {
        var line = seg
          .map(function (i, k) {
            return (k ? "L" : "M") + xAt(i).toFixed(1) + "," + yAt(nums[i]).toFixed(1);
          })
          .join("");
        var area = "";
        if (seg.length >= 2) {
          var base = (padT + innerH).toFixed(1);
          area =
            line +
            "L" + xAt(seg[seg.length - 1]).toFixed(1) + "," + base +
            "L" + xAt(seg[0]).toFixed(1) + "," + base + "Z";
        }
        var lastI = seg[seg.length - 1];
        var dot = "";
        if (lastI === nums.length - 1) {
          dot =
            '<circle cx="' + xAt(lastI).toFixed(1) + '" cy="' + yAt(nums[lastI]).toFixed(1) +
            '" r="4" fill="' + stroke + '" />';
        }
        return (
          (area ? '<path d="' + area + '" fill="url(#ddRsFill)" stroke="none"/>' : "") +
          '<path d="' + line + '" fill="none" stroke="' + stroke +
          '" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round"/>' +
          dot
        );
      })
      .join("");
    function tickLabel(i) {
      var d = dates && dates[i];
      return d ? fmtDayMonth(d) : "";
    }
    var tickIdx = [0];
    if (nums.length > 2) tickIdx.push(Math.floor((nums.length - 1) / 2));
    if (tickIdx[tickIdx.length - 1] !== nums.length - 1) tickIdx.push(nums.length - 1);
    var ticks = tickIdx
      .map(function (i) {
        var anchor = i === 0 ? "start" : i === nums.length - 1 ? "end" : "middle";
        return (
          '<text x="' + xAt(i).toFixed(1) + '" y="' + (h - 6) + '" text-anchor="' + anchor +
          '" fill="#8d8d8d" font-size="10" font-family="Plus Jakarta Sans, Inter, sans-serif">' +
          escapeHtml(tickLabel(i)) + "</text>"
        );
      })
      .join("");
    var y50 = yAt(50);
    var grid =
      '<line x1="' + padL + '" y1="' + y50.toFixed(1) + '" x2="' + (w - padR) + '" y2="' + y50.toFixed(1) +
      '" stroke="rgba(255,255,255,0.14)" stroke-dasharray="3 4"/>' +
      '<text x="' + (padL - 6) + '" y="' + (yAt(100) + 4).toFixed(1) +
      '" text-anchor="end" fill="#8d8d8d" font-size="10" font-family="Plus Jakarta Sans, Inter, sans-serif">100</text>' +
      '<text x="' + (padL - 6) + '" y="' + (y50 + 3).toFixed(1) +
      '" text-anchor="end" fill="#8d8d8d" font-size="10" font-family="Plus Jakarta Sans, Inter, sans-serif">50</text>' +
      '<text x="' + (padL - 6) + '" y="' + yAt(0).toFixed(1) +
      '" text-anchor="end" fill="#8d8d8d" font-size="10" font-family="Plus Jakarta Sans, Inter, sans-serif">0</text>';
    var aria =
      "RS Score semanal. Inicio " + fmtEsSmart(valid[0], 1) + ", fin " + fmtEsSmart(valid[valid.length - 1], 1) + ".";
    return (
      '<svg class="dd-rs-chart" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="' + escapeHtml(aria) + '">' +
      '<defs><linearGradient id="ddRsFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + stroke + '" stop-opacity="0.38"/>' +
      '<stop offset="100%" stop-color="' + stroke + '" stop-opacity="0"/>' +
      "</linearGradient></defs>" +
      grid + paths + ticks +
      "</svg>"
    );
  }

  function fichaBackButton() {
    return (
      '<button type="button" id="ficha-back" class="dd-ficha-back" aria-label="Volver al ranking">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">' +
      '<polyline points="15 18 9 12 15 6"/></svg></button>'
    );
  }

  function renderFicha(sym) {
    var root = document.getElementById("ficha");
    if (!root) return;
    if (!state.ready) {
      root.innerHTML =
        '<div class="dd-ficha-top">' + fichaBackButton() +
        '<p class="dd-ficha-empty">Cargando…</p></div>';
      return;
    }
    var row = rowBySymbol(sym);
    if (!row) {
      var msg = state.loadError || ("No hay ficha para " + sym + " en este ranking.");
      root.innerHTML =
        '<div class="dd-ficha-top">' + fichaBackButton() + "</div>" +
        '<p class="dd-ficha-empty">' + escapeHtml(msg) + "</p>";
      document.title = sym + " · Angus";
      return;
    }
    var total = state.ranking.length;
    var rank =
      row.rank != null && total
        ? "#" + row.rank + " de " + total
        : row.rank != null
          ? "#" + row.rank
          : "";
    var subBits = [];
    if (row.name) subBits.push(row.name);
    if (row.sector) subBits.push(row.sector);
    var changeCls = distClass(row.change_pct);
    var mark = gateMark(row);
    var dist = row.dist_ema200_pct;
    var slopeBits = [];
    if (row.ema200 != null) slopeBits.push("EMA200 " + fmtPrice(row.ema200));
    if (row.ema200_slope_pct != null) {
      slopeBits.push("pendiente " + fmtEsSignedPct(row.ema200_slope_pct, 2) + " en ~5 sesiones");
    }
    var range = row.range_52w;
    var rangeBlock;
    if (!range || range.low == null || range.high == null) {
      rangeBlock = '<p class="dd-ficha-empty">Sin rango de 52 semanas. Se calcula al correr build.py.</p>';
    } else {
      var pos = range.position_pct == null ? 0 : Math.max(0, Math.min(100, Number(range.position_pct)));
      var cap =
        range.sessions >= 252
          ? "Mínimo y máximo de las últimas 252 sesiones (~52 semanas)."
          : "Mínimo y máximo de las últimas " + range.sessions + " sesiones disponibles.";
      rangeBlock =
        '<div class="dd-range-head"><span>Posición en el rango de 52 semanas</span><strong>' +
        escapeHtml(range.position_pct == null ? "—" : fmtEsSmart(range.position_pct, 1) + "%") +
        "</strong></div>" +
        '<div class="dd-range-track" aria-hidden="true"><span class="dd-range-knob" style="left:' +
        pos.toFixed(1) + '%"></span></div>' +
        '<div class="dd-range-scale"><span>' + escapeHtml(fmtPrice(range.low)) + " mín.</span><span>" +
        escapeHtml(fmtPrice(range.high)) + " máx.</span></div>" +
        '<p class="dd-ficha-note">' + escapeHtml(cap) + "</p>";
    }
    var flags = row.flags || [];
    var penaltyBlock;
    if (!flags.length) {
      penaltyBlock =
        '<div class="dd-ficha-row"><span class="dd-ficha-mark is-ok" aria-hidden="true">✓</span>' +
        '<span class="dd-ficha-row-text">Sin penalizaciones activas</span></div>';
    } else {
      penaltyBlock = '<div class="dd-ficha-flags">' + formatFlags(flags) + "</div>";
    }
    var entroBlock = "";
    if (row.entro && row.entro.label) {
      entroBlock =
        '<section class="dd-ficha-card" aria-label="Entró al Top 10">' +
        '<h2 class="dd-ficha-kicker">Entró al Top 10</h2>' +
        '<p class="dd-ficha-entro">' + escapeHtml(row.entro.label) + "</p>" +
        (row.entro.censored
          ? '<p class="dd-ficha-note">La racha cubre toda la ventana reconstruida.</p>'
          : "") +
        "</section>";
    }
    var earn = earningsFor(row.symbol);
    var earnBlock = "";
    if (earn) {
      var e = earn.row;
      var when = fmtDayMonth(e.date);
      var hour = e.hour ? " · " + e.hour : "";
      earnBlock =
        '<section class="dd-ficha-card" aria-label="Resultados">' +
        '<h2 class="dd-ficha-kicker">' + (earn.upcoming ? "Próximos resultados" : "Resultados") + "</h2>" +
        '<p class="dd-ficha-entro">' + escapeHtml((when || "—") + hour) + "</p>" +
        "</section>";
    }
    var weeks =
      (row.rs_weekly && row.rs_weekly.length) ||
      (state.rsWeekly && state.rsWeekly.weeks) ||
      16;
    var caption = (state.rsWeekly && state.rsWeekly.definition) || RS_CAPTION_FALLBACK;
    var dates = (state.rsWeekly && state.rsWeekly.dates) || [];
    root.innerHTML =
      '<header class="dd-ficha-top">' +
      fichaBackButton() +
      '<div class="dd-ficha-ident">' +
      '<div class="dd-ficha-ident-row">' +
      logoHtml(row.symbol, logoFor(row), 42) +
      '<h1 class="dd-ficha-ticker">' + escapeHtml(row.symbol) + "</h1>" +
      (rank ? '<span class="dd-ficha-rank">' + escapeHtml(rank) + "</span>" : "") +
      "</div>" +
      (subBits.length ? '<p class="dd-ficha-sub">' + escapeHtml(subBits.join(" · ")) + "</p>" : "") +
      "</div>" +
      '<div class="dd-ficha-quote">' +
      '<p class="dd-ficha-price">' + escapeHtml(fmtPrice(row.close)) + "</p>" +
      '<p class="dd-ficha-change ' + changeCls + '">' + escapeHtml(fmtEsSignedPct(row.change_pct, 2)) + "</p>" +
      "</div></header>" +
      entryBlock(row) +
      analystBlock(row) +
      signalFichaBlock(row) +
      '<section class="dd-ficha-card" aria-label="Patrones">' +
      '<h2 class="dd-ficha-kicker">Patrones</h2>' +
      patternChips(row) +
      "</section>" +
      healthBlock(row) +
      insiderFichaBlock(row) +
      '<section class="dd-ficha-card" aria-label="Desk Score">' +
      '<h2 class="dd-ficha-kicker">Desk Score</h2>' +
      '<div class="dd-ficha-score">' + gaugeHtml(row.desk_score) +
      '<div class="dd-pillars">' + pillarsHtml(row) + "</div></div>" +
      penaltyFootnote(flags) +
      "</section>" +
      '<section class="dd-ficha-card" aria-label="Rango de 52 semanas">' + rangeBlock + "</section>" +
      '<section class="dd-ficha-card" aria-label="Gate de tendencia">' +
      '<h2 class="dd-ficha-kicker">Gate de tendencia</h2>' +
      '<div class="dd-ficha-row">' +
      '<span class="dd-ficha-mark ' + mark.cls + '" aria-hidden="true">' + mark.ch + "</span>" +
      '<span class="dd-ficha-row-text">' + escapeHtml(gateText(row)) + "</span>" +
      '<span class="dd-ficha-row-val ' + distClass(dist) + '">' +
      escapeHtml(dist == null ? "—" : fmtEsSignedPct(dist, 2)) + "</span></div>" +
      (slopeBits.length ? '<p class="dd-ficha-note">' + escapeHtml(slopeBits.join(" · ")) + "</p>" : "") +
      "</section>" +
      '<section class="dd-ficha-card" aria-label="Penalizaciones">' +
      '<h2 class="dd-ficha-kicker">Penalizaciones</h2>' + penaltyBlock + "</section>" +
      entroBlock +
      earnBlock +
      '<section class="dd-ficha-card" aria-label="Evolución del RS Score">' +
      '<h2 class="dd-ficha-kicker">Evolución del RS Score · últimas ' + weeks + " semanas</h2>" +
      rsChartSvg(row.rs_weekly, dates) +
      '<p class="dd-ficha-note">' + escapeHtml(caption) + "</p>" +
      "</section>" +
      '<p class="dd-ficha-disclaimer"><strong>Disclaimer:</strong> no es recomendación de compra ni de inversión.</p>';
    document.title = row.symbol + " · Angus";
  }

  var PAGE_BY_HASH = {
    "": "resumen",
    resumen: "resumen",
    hoy: "resumen",
    formulas: "resumen",
    notas: "resumen",
    score: "score",
    top10: "score",
    ranking: "score",
    sectores: "score",
    rs: "score",
    historial: "score",
    simulacion: "score",
    senales: "senales",
    patrones: "senales",
    rotacion: "rotacion",
    analisis: "analisis",
    insiders: "analisis",
    analistas: "analisis",
  };

  function routeKey() {
    var raw = (location.hash || "").replace(/^#/, "");
    try {
      raw = decodeURIComponent(raw);
    } catch (e) {}
    return raw;
  }

  function pageFromHash() {
    if (parseTickerHash()) return "analisis";
    var key = routeKey().toLowerCase();
    if (key === "señales") return "senales";
    if (key === "rotación") return "rotacion";
    if (key === "análisis" || key === "analisis") return "analisis";
    if (key === "fórmulas") return "resumen";
    return PAGE_BY_HASH[key] || "resumen";
  }

  function showPage(page) {
    state.page = page;
    document.querySelectorAll(".dd-pane").forEach(function (el) {
      el.classList.toggle("is-on", el.getAttribute("data-page") === page);
    });
    document.querySelectorAll(".dd-tabbar a").forEach(function (a) {
      var on = a.getAttribute("data-page") === page;
      a.classList.toggle("is-active", on);
      if (on) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    if (page !== "rotacion") stopRrgPlay();
    if (page === "score" && state.walkforward) {
      var sim = document.getElementById("simulacion");
      if (sim && sim.open) {
        window.requestAnimationFrame(function () { drawWalkforwardChart(state.walkforward); });
      }
    }
    if (page === "rotacion") {
      window.requestAnimationFrame(drawRrg);
    }
  }

  function renderAnalisisEmpty() {
    var root = document.getElementById("ficha");
    if (!root) return;
    root.hidden = false;
    root.innerHTML =
      '<p class="dd-ficha-empty">Elegí un ticker para ver la ficha. Podés buscarlo arriba o tocar una fila en Score, Señales o Rotación.</p>';
    if (state.baseTitle) document.title = state.baseTitle;
    state.fichaSym = null;
  }

  var lastNavHash = null;

  function renderRoute() {
    var sym = parseTickerHash();
    var hash = location.hash || "";
    var moved = hash !== lastNavHash;
    lastNavHash = hash;
    var key = routeKey();
    var page = pageFromHash();
    var enteringTicker = sym && state.fichaSym !== sym;
    showPage(page);
    if (sym) {
      state.fichaSym = sym;
      var search = document.getElementById("analisis-search");
      if (search && document.activeElement !== search) search.value = sym;
      renderFicha(sym);
      if (moved && enteringTicker) {
        window.scrollTo(0, 0);
        var back = document.getElementById("ficha-back");
        if (back) back.focus();
      }
      return;
    }
    state.fichaSym = null;
    if (state.baseTitle) document.title = state.baseTitle;
    if (page === "analisis") renderAnalisisEmpty();
    if (!moved) return;
    var foldId = key.toLowerCase();
    if (foldId === "fórmulas") foldId = "formulas";
    var fold = document.getElementById(foldId);
    if (fold && fold.tagName === "DETAILS") fold.open = true;
    var target = document.getElementById(foldId);
    if (target && foldId && foldId !== page) {
      window.setTimeout(function () {
        target.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 40);
    } else {
      window.scrollTo(0, 0);
    }
    if (foldId === "simulacion" && state.walkforward) {
      window.setTimeout(function () { drawWalkforwardChart(state.walkforward); }, 80);
    }
  }

  function goBack() {
    var hash = location.hash;
    if (!hash) return;
    if (window.history.length > 1) {
      history.back();
      window.setTimeout(function () {
        if (location.hash === hash) location.hash = "";
      }, 80);
    } else {
      location.hash = "";
    }
  }

  function openTicker(sym) {
    if (!sym) return;
    location.hash = "#/t/" + encodeURIComponent(sym);
  }

  function bindRowOpen(id) {
    var body = document.getElementById(id);
    if (!body) return;
    body.addEventListener("click", function (ev) {
      var tr = ev.target.closest("tr[data-symbol]");
      if (!tr || !body.contains(tr)) return;
      var sym = tr.getAttribute("data-symbol");
      if (sym) openTicker(sym);
    });
    body.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      var tr = ev.target.closest("tr[data-symbol]");
      if (!tr || ev.target !== tr) return;
      ev.preventDefault();
      var sym = tr.getAttribute("data-symbol");
      if (sym) openTicker(sym);
    });
  }

  function bindFichaNav() {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    bindRowOpen("ranking-body");
    bindRowOpen("top10-body");
    bindRowOpen("rs-body");
    bindRowOpen("senales-body");
    var podio = document.getElementById("podio-body");
    if (podio) {
      podio.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-symbol]");
        if (!btn || !podio.contains(btn)) return;
        openTicker(btn.getAttribute("data-symbol"));
      });
    }
    var ficha = document.getElementById("ficha");
    if (ficha) {
      ficha.addEventListener("click", function (ev) {
        if (ev.target.closest("#ficha-back")) {
          ev.preventDefault();
          goBack();
        }
      });
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && parseTickerHash()) goBack();
    });
    window.addEventListener("hashchange", renderRoute);
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", function () {
      // Ruta relativa: funciona en raíz y en sub-path (GitHub Pages /desk-dashboard/)
      navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(function (err) {
        if (window.console && console.warn) console.warn("SW no registrado:", err && err.message);
      });
    });
  }

  var wfResizeTimer = null;
  window.addEventListener("resize", function () {
    if (!state.walkforward || !state.walkforward.weeks) return;
    window.clearTimeout(wfResizeTimer);
    wfResizeTimer = window.setTimeout(function () {
      drawWalkforwardChart(state.walkforward);
    }, 120);
  });

  function syncScrollPad() {
    var bar = document.querySelector(".dd-topbar");
    if (!bar) return;
    var h = bar.offsetHeight + 8;
    document.documentElement.style.setProperty("--dd-topbar-h", h + "px");
  }

  function bindTextMore() {
    document.addEventListener("click", function (ev) {
      var btn = ev.target.closest("[data-clamp]");
      if (!btn) return;
      var el = document.getElementById(btn.getAttribute("data-clamp"));
      if (!el) return;
      var open = el.classList.toggle("is-open");
      el.classList.toggle("is-clamped", !open);
      btn.textContent = open ? "Ver menos" : "Ver más";
    });
  }

  var RRG_COLOR = {
    liderando: "#34D399",
    mejorando: "#38BDF8",
    debilitandose: "#FBBF24",
    rezagado: "#F87171",
  };
  var SIG_DAILY = [
    ["rebote_ema200", "Rebote"],
    ["cruce_ema200", "Cruce"],
    ["macd", "MACD"],
    ["rsi", "RSI"],
    ["vcp", "VCP"],
    ["pivote", "Pivote"],
    ["sobre_medias", "Medias"],
  ];
  var SIG_WEEKLY = [
    ["macd_w", "MACD"],
    ["rsi_w", "RSI"],
    ["vcp_w", "VCP"],
    ["pivote_w", "Pivote"],
  ];

  function sigCols(block) {
    var cols = (block && block.columns) || {};
    function pack(list, fallback) {
      var out = (list || []).map(function (c) {
        return [c.id, c.short || c.label || c.id];
      }).filter(function (c) { return c[0]; });
      return out.length ? out : fallback;
    }
    return { daily: pack(cols.daily, SIG_DAILY), weekly: pack(cols.weekly, SIG_WEEKLY) };
  }

  function renderPodium() {
    var root = document.getElementById("podio");
    var body = document.getElementById("podio-body");
    if (!root || !body) return;
    var rows = (state.ranking || []).filter(function (r) { return r && r.rank != null; });
    rows.sort(function (a, b) { return Number(a.rank) - Number(b.rank); });
    rows = rows.slice(0, 3);
    if (!rows.length) {
      root.hidden = true;
      body.innerHTML = "";
      return;
    }
    root.hidden = false;
    body.innerHTML = rows.map(function (r, i) {
      var sub = [r.name, r.sector].filter(Boolean).join(" · ");
      var score = i === 0
        ? gaugeHtml(r.desk_score)
        : '<p class="dd-podio-score">' + escapeHtml(r.desk_score == null ? "—" : fmtEsSmart(r.desk_score, 1)) + "</p>";
      return (
        '<button type="button" class="dd-podio-card' + (i === 0 ? " is-first" : "") +
        '" data-symbol="' + escapeHtml(r.symbol) + '">' +
        '<span class="dd-podio-pos">' + (i + 1) + "</span>" +
        score +
        '<span class="dd-podio-id">' + logoHtml(r.symbol, logoFor(r), i === 0 ? 36 : 28) +
        "<span><strong>" + escapeHtml(r.symbol) + "</strong>" +
        (sub ? "<em>" + escapeHtml(sub) + "</em>" : "") +
        "</span></span></button>"
      );
    }).join("");
  }

  function renderSignals(block) {
    state.signalsBlock = block || null;
    var head = document.getElementById("senales-head");
    var body = document.getElementById("senales-body");
    var lists = document.getElementById("senales-lists");
    var def = document.getElementById("senales-def");
    if (def) {
      def.textContent = (block && block.definition) ||
        "Sale del precio que ya baja Angus. Una lectura activa no es una compra.";
    }
    var cols = sigCols(block);
    if (head) {
      function ths(list) {
        return list.map(function (c) {
          return '<th scope="col">' + escapeHtml(c[1]) + "</th>";
        }).join("");
      }
      head.innerHTML =
        "<tr>" +
        '<th scope="col" class="dd-sticky-col dd-col-ticker" rowspan="2">Ticker</th>' +
        '<th scope="colgroup" colspan="' + cols.daily.length + '">Diario</th>' +
        '<th scope="colgroup" colspan="' + cols.weekly.length + '">Semanal</th>' +
        '<th scope="col" rowspan="2">RS</th>' +
        "</tr><tr>" + ths(cols.daily) + ths(cols.weekly) + "</tr>";
    }
    var rows = (block && block.rows) || [];
    if (body) {
      if (!rows.length) {
        body.innerHTML = '<tr><td colspan="14" class="dd-empty">Sin matriz en esta publicación. Se calcula al correr build.py.</td></tr>';
      } else {
        body.innerHTML = rows.map(function (r) {
          function dots(list) {
            return list.map(function (c) {
              var on = r.signals && r.signals[c[0]];
              return '<td><span class="dd-sigdot' + (on ? " is-on" : "") + '" title="' +
                escapeHtml(c[1] + (on ? ": activa" : ": no")) + '"></span></td>';
            }).join("");
          }
          var count = r.count != null ? r.count : 0;
          return (
            '<tr data-symbol="' + escapeHtml(r.symbol) + '" tabindex="0" role="link" aria-label="Ver ficha de ' +
            escapeHtml(r.symbol) + '"><td class="dd-sticky-col dd-col-ticker"><span class="dd-sig-ticker">' +
            tickerWithLogo(r, "dd-ticker") +
            '<span class="dd-sig-n' + (count >= 4 ? " is-hot" : "") + '" title="Lecturas activas">' +
            escapeHtml(String(count)) + "</span></span></td>" +
            dots(cols.daily) + dots(cols.weekly) +
            "<td>" + escapeHtml(r.rs_score == null ? "—" : fmtNum(r.rs_score, 1)) + "</td></tr>"
          );
        }).join("");
      }
    }
    if (!lists) return;
    var groups = (block && block.lists) || [];
    if (!block) {
      lists.innerHTML = '<p class="dd-empty">Las listas por señal aparecen cuando build.py publica la matriz.</p>';
      return;
    }
    var html = groups.map(function (g) {
      var items = (g.rows || []).map(function (r) {
        return linkRow(r, r.detail || "");
      }).join("");
      var marco = g.timeframe === "W" ? "Semanal" : "Diario";
      return (
        '<section class="dd-sig-list"><h3>' + escapeHtml(g.label) +
        ' <span class="dd-sig-count">' + escapeHtml(marco + " · " + g.count) + "</span></h3>" +
        '<div class="dd-link-list">' + items + "</div></section>"
      );
    }).join("");
    if (block.quiet && block.quiet.length) {
      html += '<p class="dd-sig-quiet">Sin lecturas: ' + escapeHtml(block.quiet.join(", ")) + ".</p>";
    }
    if (block.limitation) {
      html += '<p class="dd-sig-quiet">' + escapeHtml(block.limitation) + "</p>";
    }
    lists.innerHTML = html || '<p class="dd-empty">Ninguna lectura activa con estos umbrales.</p>';
  }

  function signalFichaBlock(row) {
    var block = state.signalsBlock;
    if (!block || !row) return "";
    var hit = null;
    (block.rows || []).forEach(function (r) {
      if (String(r.symbol) === String(row.symbol)) hit = r;
    });
    if (!hit) return "";
    var cols = sigCols(block);
    var on = cols.daily.concat(cols.weekly).filter(function (c) {
      return hit.signals && hit.signals[c[0]];
    });
    var chips = on.length
      ? '<div class="dd-sig-chips">' + on.map(function (c) {
        return '<span class="dd-sig-chip">' + escapeHtml(c[1]) + "</span>";
      }).join("") + "</div>"
      : '<p class="dd-ficha-empty">Sin lecturas activas en esta rueda.</p>';
    return (
      '<section class="dd-ficha-card" aria-label="Señales">' +
      '<h2 class="dd-ficha-kicker">Señales · ' + escapeHtml(String(hit.count || 0)) + "</h2>" +
      chips +
      '<p class="dd-ficha-note">Lectura del precio. No es una recomendación de compra.</p></section>'
    );
  }

  function rrgSeries() {
    var all = (state.rrg && state.rrg.series) || [];
    var f = state.rrgFilter || "sector";
    return all.filter(function (s) {
      if (f === "all") return true;
      if (f === "stock") return s.group === "stock";
      if (f === "etf") return s.group === "sector" || s.group === "benchmark";
      return s.group === "sector";
    });
  }

  function stopRrgPlay() {
    if (state.rrgTimer) {
      window.clearInterval(state.rrgTimer);
      state.rrgTimer = null;
    }
    var btn = document.getElementById("rrg-play");
    if (btn) {
      btn.textContent = "Play";
      btn.setAttribute("aria-pressed", "false");
    }
  }

  function renderRrgNotes() {
    var ul = document.getElementById("rrg-notes");
    if (!ul) return;
    var timeline = state.rrg && state.rrg.notes_by_date;
    var notes;
    if (timeline && timeline.length) {
      var i = Math.max(0, Math.min(timeline.length - 1, state.rrgFrame || 0));
      notes = timeline[i] || [];
      if (!notes.length) {
        notes = ["Esta semana ningún ETF de sector cambió de cuadrante respecto del SPY."];
      }
    } else {
      notes = (state.rrg && state.rrg.notes) || [];
    }
    ul.innerHTML = notes.map(function (n) {
      return "<li>" + escapeHtml(n) + "</li>";
    }).join("");
  }

  function renderRrg(block) {
    state.rrg = block || null;
    var dates = (block && block.dates) || [];
    var max = Math.max(0, dates.length - 1);
    var slider = document.getElementById("rrg-slider");
    if (!state.rrgTimer) state.rrgFrame = frameFromQuery(max);
    if (state.rrgFrame > max) state.rrgFrame = max;
    if (slider) {
      slider.max = String(max);
      slider.value = String(state.rrgFrame);
      slider.disabled = dates.length < 2;
    }
    var def = document.getElementById("rrg-def");
    if (def) {
      def.textContent = (block && block.definition) ||
        "Rotación relativa contra el SPY, con cierres semanales. El centro es 100.";
    }
    renderRrgNotes();
    drawRrg();
  }

  function frameFromQuery(max) {
    var raw = "";
    try {
      raw = new URLSearchParams(location.search).get("frame") || "";
    } catch (e) {
      raw = "";
    }
    if (raw === "") return max;
    var n = Number(raw);
    if (Number.isNaN(n)) return max;
    return Math.max(0, Math.min(max, Math.round(n)));
  }

  function rrgFrameLabel() {
    var dates = (state.rrg && state.rrg.dates) || [];
    var el = document.getElementById("rrg-frame-label");
    if (!el) return;
    if (!dates.length) {
      el.textContent = "—";
      return;
    }
    var i = Math.max(0, Math.min(dates.length - 1, state.rrgFrame || 0));
    el.textContent = fmtDayMonth(dates[i]) + " · " + (i + 1) + "/" + dates.length;
  }

  function drawRrg() {
    var host = document.getElementById("rrg-chart");
    if (!host) return;
    var tip = document.getElementById("rrg-tip");
    if (tip) tip.hidden = true;
    rrgFrameLabel();
    renderRrgNotes();
    var dates = (state.rrg && state.rrg.dates) || [];
    var series = rrgSeries();
    var labels = (state.rrg && state.rrg.quadrants) || {
      liderando: "Liderando",
      debilitandose: "Debilitándose",
      rezagado: "Rezagado",
      mejorando: "Mejorando",
    };
    if (!dates.length || !series.length) {
      host.innerHTML = '<p class="dd-empty">Sin curva de rotación en esta publicación. Hacen falta varias semanas de cierres.</p>';
      host.setAttribute("aria-label", "Sin gráfico de rotación");
      return;
    }
    var frame = Math.max(0, Math.min(dates.length - 1, state.rrgFrame || 0));
    var tail = (state.rrg && state.rrg.tail) || 12;
    var valsX = [];
    var valsY = [];
    series.forEach(function (s) {
      (s.points || []).forEach(function (p) {
        if (!p) return;
        valsX.push(Number(p.ratio));
        valsY.push(Number(p.momentum));
      });
    });
    if (!valsX.length) {
      host.innerHTML = '<p class="dd-empty">Estos nombres todavía no tienen puntos en la ventana.</p>';
      return;
    }
    function extent(vals) {
      var min = 100;
      var max = 100;
      vals.forEach(function (v) {
        if (v < min) min = v;
        if (v > max) max = v;
      });
      var span = Math.max(4, max - min);
      var pad = span * 0.14;
      return [min - pad, max + pad];
    }
    var xDom = extent(valsX);
    var yDom = extent(valsY);
    var w = 640;
    var h = 420;
    var padL = 52;
    var padR = 18;
    var padT = 28;
    var padB = 42;
    var innerW = w - padL - padR;
    var innerH = h - padT - padB;
    function xAt(v) {
      return padL + ((v - xDom[0]) / (xDom[1] - xDom[0])) * innerW;
    }
    function yAt(v) {
      return padT + (1 - (v - yDom[0]) / (yDom[1] - yDom[0])) * innerH;
    }
    var xMid = xAt(100);
    var yMid = yAt(100);
    var quads =
      '<rect x="' + padL + '" y="' + padT + '" width="' + (xMid - padL) + '" height="' + (yMid - padT) + '" fill="rgba(56,189,248,0.08)"/>' +
      '<rect x="' + xMid + '" y="' + padT + '" width="' + (padL + innerW - xMid) + '" height="' + (yMid - padT) + '" fill="rgba(52,211,153,0.08)"/>' +
      '<rect x="' + padL + '" y="' + yMid + '" width="' + (xMid - padL) + '" height="' + (padT + innerH - yMid) + '" fill="rgba(248,113,113,0.08)"/>' +
      '<rect x="' + xMid + '" y="' + yMid + '" width="' + (padL + innerW - xMid) + '" height="' + (padT + innerH - yMid) + '" fill="rgba(251,191,36,0.08)"/>';
    function qLabel(text, x, y, anchor) {
      return '<text x="' + x + '" y="' + y + '" text-anchor="' + anchor +
        '" fill="#8d8d8d" font-size="11" font-family="Plus Jakarta Sans, Inter, sans-serif">' +
        escapeHtml(text) + "</text>";
    }
    var names =
      qLabel(labels.mejorando || "Mejorando", padL + 8, padT + 16, "start") +
      qLabel(labels.liderando || "Liderando", padL + innerW - 8, padT + 16, "end") +
      qLabel(labels.rezagado || "Rezagado", padL + 8, padT + innerH - 8, "start") +
      qLabel(labels.debilitandose || "Debilitándose", padL + innerW - 8, padT + innerH - 8, "end");
    var axes =
      '<line x1="' + xMid.toFixed(1) + '" y1="' + padT + '" x2="' + xMid.toFixed(1) + '" y2="' + (padT + innerH) + '" stroke="rgba(255,255,255,0.28)"/>' +
      '<line x1="' + padL + '" y1="' + yMid.toFixed(1) + '" x2="' + (padL + innerW) + '" y2="' + yMid.toFixed(1) + '" stroke="rgba(255,255,255,0.28)"/>' +
      '<text x="' + padL + '" y="16" fill="#a0a0a0" font-size="11" font-family="Plus Jakarta Sans, Inter, sans-serif">RS-Momentum ↑</text>' +
      '<text x="' + (padL + innerW) + '" y="' + (h - 8) + '" text-anchor="end" fill="#a0a0a0" font-size="11" font-family="Plus Jakarta Sans, Inter, sans-serif">RS-Ratio →</text>';
    var showNames = state.rrgFilter !== "stock" && state.rrgFilter !== "all";
    var trails = series.map(function (s) {
      var pts = s.points || [];
      var chunks = [];
      var cur = [];
      var from = Math.max(0, frame - tail + 1);
      for (var i = from; i <= frame && i < pts.length; i++) {
        if (!pts[i]) {
          if (cur.length) chunks.push(cur);
          cur = [];
        } else {
          cur.push(pts[i]);
        }
      }
      if (cur.length) chunks.push(cur);
      var head = frame < pts.length ? pts[frame] : null;
      var color = RRG_COLOR[(head && head.quadrant) || "liderando"] || "#34D399";
      var lines = chunks.map(function (chunk) {
        if (chunk.length < 2) return "";
        var d = chunk.map(function (p, k) {
          return (k ? "L" : "M") + xAt(p.ratio).toFixed(1) + "," + yAt(p.momentum).toFixed(1);
        }).join("");
        return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="1.6" stroke-opacity="0.55" stroke-linecap="round" stroke-linejoin="round"/>';
      }).join("");
      if (!head) return lines;
      var cx = xAt(head.ratio);
      var cy = yAt(head.momentum);
      var rad = s.group === "stock" ? 4.2 : 6.4;
      var name = "";
      if (showNames || s.group === "sector") {
        if (state.rrgFilter !== "stock") {
          var anchor = cx > w - 78 ? "end" : "start";
          var lx = anchor === "end" ? cx - 8 : cx + 8;
          name = '<text x="' + lx.toFixed(1) + '" y="' + (cy + 4).toFixed(1) + '" text-anchor="' + anchor +
            '" fill="#f5f5f5" font-size="11" font-weight="600" font-family="Plus Jakarta Sans, Inter, sans-serif">' +
            escapeHtml(s.symbol) + "</text>";
        }
      }
      var tip = escapeHtml(s.symbol + " · " + (labels[head.quadrant] || head.quadrant));
      return lines +
        '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + rad + '" fill="' + color + '"/>' +
        '<circle class="dd-rrg-hit" data-rrg-symbol="' + escapeHtml(s.symbol) +
        '" data-rrg-name="' + escapeHtml(s.display || s.name || s.symbol) +
        '" data-rrg-ratio="' + escapeHtml(fmtEsNum(head.ratio, 2)) +
        '" data-rrg-mom="' + escapeHtml(fmtEsNum(head.momentum, 2)) +
        '" data-rrg-quad="' + escapeHtml(labels[head.quadrant] || head.quadrant) +
        '" data-rrg-date="' + escapeHtml(fmtDayMonth(head.date)) +
        '" cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="16" fill="transparent"><title>' + tip + "</title></circle>" +
        name;
    }).join("");
    host.innerHTML =
      '<svg class="dd-rrg-svg" viewBox="0 0 ' + w + " " + h + '" role="img" aria-label="Rotación relativa al ' +
      escapeHtml(fmtDayMonth(dates[frame])) + '">' +
      quads + names + axes + trails + "</svg>";
  }

  function showRrgTip(hit, ev) {
    var tip = document.getElementById("rrg-tip");
    var stage = document.querySelector(".dd-rrg-stage");
    if (!tip || !stage || !hit) return;
    tip.innerHTML =
      "<strong>" + escapeHtml(hit.getAttribute("data-rrg-symbol") || "") + "</strong>" +
      "<span>" + escapeHtml(hit.getAttribute("data-rrg-name") || "") + "</span>" +
      "<span>" + escapeHtml(hit.getAttribute("data-rrg-quad") || "") + " · " +
      escapeHtml(hit.getAttribute("data-rrg-date") || "") + "</span>" +
      "<span>RS-Ratio " + escapeHtml(hit.getAttribute("data-rrg-ratio") || "—") +
      " · RS-Momentum " + escapeHtml(hit.getAttribute("data-rrg-mom") || "—") + "</span>";
    tip.hidden = false;
    var rect = stage.getBoundingClientRect();
    var left = (ev.clientX - rect.left) + 12;
    var top = (ev.clientY - rect.top) - 72;
    if (left > rect.width - 190) left = rect.width - 200;
    if (left < 8) left = 8;
    if (top < 8) top = 8;
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  function bindSectionNav() {
    var sim = document.getElementById("simulacion");
    if (sim) {
      sim.addEventListener("toggle", function () {
        if (sim.open && state.walkforward) drawWalkforwardChart(state.walkforward);
      });
    }
    var clearBtn = document.getElementById("today-clear-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        state.flags.solo_verdes = true;
        document.querySelectorAll('.dd-chip-toggle[data-flag="solo_verdes"]').forEach(function (btn) {
          btn.classList.add("is-active");
          btn.setAttribute("aria-pressed", "true");
        });
        applyFilters();
        if ((location.hash || "") === "#ranking") {
          var ranking = document.getElementById("ranking");
          if (ranking && ranking.scrollIntoView) ranking.scrollIntoView({ behavior: "smooth", block: "start" });
        } else {
          location.hash = "#ranking";
        }
      });
    }
    var filters = document.getElementById("rrg-filters");
    if (filters) {
      filters.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-rrg]");
        if (!btn || !filters.contains(btn)) return;
        state.rrgFilter = btn.getAttribute("data-rrg") || "sector";
        filters.querySelectorAll("[data-rrg]").forEach(function (chip) {
          chip.classList.toggle("is-active", chip === btn);
        });
        var tip = document.getElementById("rrg-tip");
        if (tip) tip.hidden = true;
        drawRrg();
      });
    }
    var play = document.getElementById("rrg-play");
    if (play) {
      play.addEventListener("click", function () {
        var dates = (state.rrg && state.rrg.dates) || [];
        if (dates.length < 2) return;
        if (state.rrgTimer) {
          stopRrgPlay();
          return;
        }
        if (state.rrgFrame >= dates.length - 1) state.rrgFrame = 0;
        play.textContent = "Pausa";
        play.setAttribute("aria-pressed", "true");
        state.rrgTimer = window.setInterval(function () {
          var max = dates.length - 1;
          state.rrgFrame += 1;
          if (state.rrgFrame >= max) {
            state.rrgFrame = max;
            stopRrgPlay();
          }
          var slider = document.getElementById("rrg-slider");
          if (slider) slider.value = String(state.rrgFrame);
          drawRrg();
        }, 700);
        drawRrg();
      });
    }
    var slider = document.getElementById("rrg-slider");
    if (slider) {
      slider.addEventListener("input", function () {
        stopRrgPlay();
        state.rrgFrame = Number(slider.value) || 0;
        drawRrg();
      });
    }
    var chart = document.getElementById("rrg-chart");
    if (chart) {
      chart.addEventListener("click", function (ev) {
        var hit = ev.target.closest("[data-rrg-symbol]");
        var tip = document.getElementById("rrg-tip");
        if (!hit) {
          if (tip) tip.hidden = true;
          return;
        }
        showRrgTip(hit, ev);
      });
      chart.addEventListener("mousemove", function (ev) {
        var hit = ev.target.closest("[data-rrg-symbol]");
        if (!hit) return;
        showRrgTip(hit, ev);
      });
    }
    var stage = document.querySelector(".dd-rrg-stage");
    if (stage) {
      stage.addEventListener("mouseleave", function () {
        var tip = document.getElementById("rrg-tip");
        if (tip) tip.hidden = true;
      });
    }
    var search = document.getElementById("analisis-search");
    var suggest = document.getElementById("analisis-suggest");
    function paintSuggest() {
      if (!suggest || !search) return;
      var q = String(search.value || "").trim().toUpperCase();
      if (!q) {
        suggest.hidden = true;
        suggest.innerHTML = "";
        return;
      }
      var hits = (state.ranking || []).filter(function (r) {
        return String(r.symbol || "").toUpperCase().indexOf(q) !== -1 ||
          String(r.name || "").toUpperCase().indexOf(q) !== -1;
      }).slice(0, 8);
      if (!hits.length) {
        suggest.hidden = false;
        suggest.innerHTML = '<p class="dd-empty">Ningún ticker con ese texto.</p>';
        return;
      }
      suggest.hidden = false;
      suggest.innerHTML = hits.map(function (r) {
        return '<button type="button" data-symbol="' + escapeHtml(r.symbol) + '">' +
          logoHtml(r.symbol, logoFor(r), 22) +
          "<strong>" + escapeHtml(r.symbol) + "</strong><span>" + escapeHtml(r.name || "") + "</span></button>";
      }).join("");
    }
    if (search) {
      search.addEventListener("input", paintSuggest);
      search.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter") return;
        ev.preventDefault();
        var q = String(search.value || "").trim().toUpperCase();
        var exact = (state.ranking || []).filter(function (r) {
          return String(r.symbol || "").toUpperCase() === q;
        })[0];
        if (exact) openTicker(exact.symbol);
      });
    }
    if (suggest) {
      suggest.addEventListener("click", function (ev) {
        var btn = ev.target.closest("[data-symbol]");
        if (!btn || !suggest.contains(btn)) return;
        openTicker(btn.getAttribute("data-symbol"));
        suggest.hidden = true;
      });
    }
    syncScrollPad();
    window.addEventListener("resize", syncScrollPad);
  }

  registerServiceWorker();
  bindFilters();
  bindRefresh();
  bindFichaNav();
  bindPatternTabs();
  bindTextMore();
  bindSectionNav();
  renderRoute();
  loadData({ silent: false }).then(startAuto);
})();
