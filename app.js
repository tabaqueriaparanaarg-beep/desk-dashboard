/* Desk Dashboard — carga datos.json y pinta KPIs / top10 / earnings / ranking */
(function () {
  "use strict";

  var AUTO_MS = 5 * 60 * 1000;
  var state = {
    ranking: [],
    logos: {},
    earnings: [],
    rsWeekly: null,
    kind: "",
    flags: { above_ema200: false, rs_gt_70: false },
    search: "",
    autoTimer: null,
    loading: false,
    ready: false,
    loadError: "",
    fichaSym: null,
    listScroll: 0,
    baseTitle: "",
  };

  var PILLAR_SPEC = [
    { key: "tendencia", label: "Tendencia", max: 25 },
    { key: "fuerza_rs", label: "Fuerza RS", max: 30 },
    { key: "contraccion", label: "Contracción", max: 30 },
    { key: "setup", label: "Setup", max: 15 },
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

    setText("generated-at", data.generated_at || "—");
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
      chip.innerHTML =
        tickerWithLogo(e, "dd-earn-sym") +
        '<span class="dd-earn-date">' + escapeHtml(e.date || "") + "</span>" +
        (e.hour ? '<span class="dd-earn-hour">' + escapeHtml(e.hour) + "</span>" : "");
      strip.appendChild(chip);
    });
  }

  function filteredRanking() {
    var q = (state.search || "").trim().toUpperCase();
    return state.ranking.filter(function (r) {
      if (state.kind && r.kind !== state.kind) return false;
      if (state.flags.above_ema200 && !r.above_ema200) return false;
      if (state.flags.rs_gt_70 && !((r.rs_score || 0) > 70)) return false;
      if (q && String(r.symbol || "").toUpperCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function updateFilterCount(shown, total) {
    setText("filter-count", "Mostrando " + shown + " de " + total);
  }


  var FLAG_LABELS = {
    extendido_vs_ema200: "Extendido",
    atr_elevado: "ATR alto",
    posible_distribucion: "Distribución",
    rsi_sobrecompra: "RSI alto",
    rsi_sobreventa: "RSI bajo",
  };

  function formatFlags(flags) {
    if (!flags || !flags.length) {
      return '<span class="dd-flags-empty">—</span>';
    }
    return (
      '<span class="dd-flags">' +
      flags
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
        .join("") +
      "</span>"
    );
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
        '<span class="dd-score' + scoreTierClass(r.desk_score) + '">' + fmtNum(r.desk_score, 1) + "</span>",
        entroInline(r.entro),
        formatFlags(r.flags),
        fmtNum(p.tendencia, 1),
        fmtNum(r.rs_score, 1),
        fmtNum(p.contraccion, 1),
        fmtNum(p.setup, 1),
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
        if (i === 2) td.setAttribute("data-col", "score");
        if (i === 3) td.setAttribute("data-col", "entro");
        if (i === 4) td.setAttribute("data-col", "flags");
        if (i === 5) td.setAttribute("data-col", "tendencia");
        if (i === 6) td.setAttribute("data-col", "rs");
        if (i === 7) td.setAttribute("data-col", "contraccion");
        if (i === 8) td.setAttribute("data-col", "setup");
        if (i === 9) td.setAttribute("data-col", "dist_ema200");
        if (i === 10) td.setAttribute("data-col", "vol_rel");
        if (i === 11) td.setAttribute("data-col", "kind");
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
    el.textContent = "UI " + hh + ":" + mm + ":" + ss;
  }

  function setLoading(on) {
    state.loading = !!on;
    var btn = document.getElementById("btn-refresh");
    if (!btn) return;
    btn.disabled = !!on;
    btn.classList.toggle("is-loading", !!on);
    btn.textContent = on ? "Actualizando…" : "Actualizar";
  }

  function applyData(data) {
    state.ranking = data.ranking || [];
    state.logos = data.logos || {};
    state.earnings = data.earnings || [];
    state.rsWeekly = data.rs_weekly || null;
    state.ready = true;
    state.loadError = "";
    renderKpis(data);
    renderTop10(data.top10_return);
    renderEarnings(data.earnings);
    applyFilters();
    renderNotes(data.notes);
    state.baseTitle = "Desk Dashboard — " + ((data.kpis && data.kpis.activos) || "?") + " activos";
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
      document.title = sym + " · Desk Dashboard";
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
    document.title = row.symbol + " · Desk Dashboard";
  }

  function renderRoute() {
    var sym = parseTickerHash();
    var ficha = document.getElementById("ficha");
    if (!sym) {
      var was = document.body.classList.contains("is-ficha");
      document.body.classList.remove("is-ficha");
      if (ficha) {
        ficha.hidden = true;
        ficha.innerHTML = "";
      }
      if (state.baseTitle) document.title = state.baseTitle;
      if (was) window.scrollTo(0, state.listScroll || 0);
      state.fichaSym = null;
      return;
    }
    var entering = state.fichaSym !== sym || !document.body.classList.contains("is-ficha");
    if (entering && !document.body.classList.contains("is-ficha")) {
      state.listScroll = window.scrollY || 0;
    }
    state.fichaSym = sym;
    document.body.classList.add("is-ficha");
    if (ficha) ficha.hidden = false;
    renderFicha(sym);
    if (entering) {
      window.scrollTo(0, 0);
      var back = document.getElementById("ficha-back");
      if (back) back.focus();
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

  registerServiceWorker();
  bindFilters();
  bindRefresh();
  bindFichaNav();
  renderRoute();
  loadData({ silent: false }).then(startAuto);
})();
