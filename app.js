/* Desk Dashboard — carga datos.json y pinta KPIs / top10 / earnings / ranking */
(function () {
  "use strict";

  var AUTO_MS = 5 * 60 * 1000;
  var state = {
    ranking: [],
    logos: {},
    kind: "",
    flags: { above_ema200: false, rs_gt_70: false },
    search: "",
    autoTimer: null,
    loading: false,
  };

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

  function logoHtml(sym, src) {
    var ini = escapeHtml(tickerInitials(sym));
    if (!src) {
      return '<span class="dd-tlogo dd-tlogo-fallback" aria-hidden="true">' + ini + "</span>";
    }
    return (
      '<span class="dd-tlogo" aria-hidden="true" data-initials="' + ini + '">' +
      '<img src="' + escapeHtml(src) + '" alt="" loading="lazy" decoding="async" width="20" height="20" />' +
      "</span>"
    );
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
    setText("generated-at", "Error");
    var strip = document.getElementById("earnings-strip");
    if (strip) {
      strip.innerHTML = "";
      var p = document.createElement("p");
      p.className = "dd-empty";
      p.textContent = msg;
      strip.appendChild(p);
    }
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
    renderKpis(data);
    renderTop10(data.top10_return);
    renderEarnings(data.earnings);
    applyFilters();
    renderNotes(data.notes);
    document.title = "Desk Dashboard — " + ((data.kpis && data.kpis.activos) || "?") + " activos";
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
  loadData({ silent: false }).then(startAuto);
})();
