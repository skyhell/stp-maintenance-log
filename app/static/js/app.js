/* Global UI helpers: theme, geolocation, speech input. */
(function () {
  "use strict";

  // ---------- Theme (persisted in localStorage) ----------
  const THEME_KEY = "stp-theme";
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
  }
  function initTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored) {
      applyTheme(stored);
    } else {
      const prefersDark =
        window.matchMedia &&
        window.matchMedia("(prefers-color-scheme: dark)").matches;
      applyTheme(prefersDark ? "dark" : "light");
    }
  }
  window.toggleTheme = function () {
    const current =
      document.documentElement.getAttribute("data-theme") || "light";
    const next = current === "dark" ? "light" : "dark";
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  };
  initTheme();

  // ---------- Geolocation ----------
  // Fills #latitude and #longitude (and optionally reverse-geocode is skipped
  // for privacy). Requires HTTPS (or localhost) in modern browsers.
  window.captureLocation = function (btn) {
    const latEl = document.getElementById("latitude");
    const lonEl = document.getElementById("longitude");
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by this browser.");
      return;
    }
    const original = btn ? btn.textContent : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "…";
    }
    navigator.geolocation.getCurrentPosition(
      function (pos) {
        if (latEl) latEl.value = pos.coords.latitude.toFixed(6);
        if (lonEl) lonEl.value = pos.coords.longitude.toFixed(6);
        if (btn) {
          btn.disabled = false;
          btn.textContent = original;
        }
      },
      function (err) {
        alert("Location error: " + err.message);
        if (btn) {
          btn.disabled = false;
          btn.textContent = original;
        }
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
  };

  // ---------- Speech input (Web Speech API) ----------
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  window.speechSupported = !!SpeechRecognition;

  window.startSpeech = function (targetId, btn, lang) {
    if (!SpeechRecognition) {
      alert(btn ? btn.getAttribute("data-unsupported") : "Not supported");
      return;
    }
    const target = document.getElementById(targetId);
    if (!target) return;

    const recog = new SpeechRecognition();
    recog.lang = lang || document.documentElement.lang || "de-DE";
    recog.interimResults = false;
    recog.maxAlternatives = 1;

    const listeningLabel = btn ? btn.getAttribute("data-listening") : "";
    const idleLabel = btn ? btn.textContent : "";

    recog.onstart = function () {
      if (btn) {
        btn.classList.add("listening");
        btn.textContent = listeningLabel || "…";
      }
    };
    recog.onresult = function (event) {
      const text = event.results[0][0].transcript;
      const sep = target.value && !target.value.endsWith(" ") ? " " : "";
      target.value = target.value + sep + text;
      target.dispatchEvent(new Event("input", { bubbles: true }));
    };
    recog.onerror = function () {
      /* silently ignore; user can retry */
    };
    recog.onend = function () {
      if (btn) {
        btn.classList.remove("listening");
        btn.textContent = idleLabel;
      }
    };
    recog.start();
  };

  // Hide speech buttons when unsupported.
  document.addEventListener("DOMContentLoaded", function () {
    if (!SpeechRecognition) {
      document.querySelectorAll(".speech-btn").forEach(function (b) {
        b.style.display = "none";
      });
    }
  });

  // ---------- Quick-select year vs. custom date range ----------
  // The server gives a chosen year precedence over from/to dates. Keep the
  // form unambiguous: picking a date resets the year select to "all", and
  // picking a year clears the date fields.
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form").forEach(function (form) {
      const yearSel = form.querySelector('select[name="year"]');
      const from = form.querySelector('input[name="date_from"]');
      const to = form.querySelector('input[name="date_to"]');
      if (!yearSel || (!from && !to)) return;

      [from, to].forEach(function (input) {
        if (!input) return;
        input.addEventListener("change", function () {
          if (input.value) yearSel.value = "";
        });
      });
      yearSel.addEventListener("change", function () {
        if (yearSel.value) {
          if (from) from.value = "";
          if (to) to.value = "";
        }
      });
    });
  });

  // ---------- Enlarge measurement charts on click ----------
  document.addEventListener("DOMContentLoaded", function () {
    const cards = document.querySelectorAll(".chart-card.zoomable");
    if (!cards.length) return;
    const grid = document.querySelector(".chart-grid[data-close-label]");
    const closeLabel = grid ? grid.getAttribute("data-close-label") : "Close";
    const hintLabel = grid ? grid.getAttribute("data-hint-label") : "";
    const SVG_NS = "http://www.w3.org/2000/svg";

    // In the enlarged chart, clicking reads off the nearest point's x/y values
    // with a crosshair down to each axis.
    function enableReadout(svg) {
      const axisX = parseFloat(svg.getAttribute("data-axis-x"));
      const axisY = parseFloat(svg.getAttribute("data-axis-y"));
      const vw = svg.viewBox.baseVal.width;
      const pts = Array.prototype.map.call(
        svg.querySelectorAll(".pt"),
        function (g) {
          return {
            cx: parseFloat(g.getAttribute("data-cx")),
            cy: parseFloat(g.getAttribute("data-cy")),
            date: g.getAttribute("data-date"),
            value: g.getAttribute("data-value"),
          };
        }
      );
      if (!pts.length || isNaN(axisX)) return;
      svg.style.cursor = "crosshair";
      let layer = null;

      function el(name, attrs) {
        const n = document.createElementNS(SVG_NS, name);
        for (const k in attrs) n.setAttribute(k, attrs[k]);
        return n;
      }
      function show(pt) {
        if (layer) layer.remove();
        layer = el("g", { class: "xhair" });
        layer.appendChild(
          el("line", { class: "xhair-line", x1: pt.cx, y1: pt.cy, x2: pt.cx, y2: axisY })
        );
        layer.appendChild(
          el("line", { class: "xhair-line", x1: pt.cx, y1: pt.cy, x2: axisX, y2: pt.cy })
        );
        layer.appendChild(el("circle", { class: "xhair-dot", cx: pt.cx, cy: pt.cy, r: 5 }));

        const w = Math.max(pt.date.length, pt.value.length) * 5.6 + 14;
        const h = 30;
        let bx = pt.cx + 10;
        let by = pt.cy - h - 8;
        if (bx + w > vw - 2) bx = pt.cx - w - 10;
        if (by < 2) by = pt.cy + 10;
        layer.appendChild(el("rect", { class: "xhair-box", x: bx, y: by, width: w, height: h, rx: 6 }));
        const dt = el("text", { class: "xhair-text", x: bx + 7, y: by + 13 });
        dt.textContent = pt.date;
        layer.appendChild(dt);
        const vt = el("text", { class: "xhair-text xhair-value", x: bx + 7, y: by + 25 });
        vt.textContent = pt.value;
        layer.appendChild(vt);
        svg.appendChild(layer);
      }
      svg.addEventListener("click", function (evt) {
        const p = svg.createSVGPoint();
        p.x = evt.clientX;
        p.y = evt.clientY;
        const loc = p.matrixTransform(svg.getScreenCTM().inverse());
        let best = pts[0];
        let bestDist = Infinity;
        pts.forEach(function (pt) {
          const d = Math.abs(pt.cx - loc.x);
          if (d < bestDist) {
            bestDist = d;
            best = pt;
          }
        });
        show(best);
      });
    }

    function open(card) {
      const backdrop = document.createElement("div");
      backdrop.className = "chart-modal-backdrop";

      const modal = document.createElement("div");
      modal.className = "chart-modal";

      const closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.className = "chart-modal-close";
      closeBtn.innerHTML = "✕";
      closeBtn.setAttribute("aria-label", closeLabel);
      closeBtn.title = closeLabel;

      const inner = document.createElement("div");
      inner.className = "chart-modal-body";
      inner.innerHTML = card.innerHTML;

      if (hintLabel) {
        const hint = document.createElement("p");
        hint.className = "chart-modal-hint";
        hint.textContent = hintLabel;
        inner.appendChild(hint);
      }

      modal.appendChild(closeBtn);
      modal.appendChild(inner);
      backdrop.appendChild(modal);
      document.body.appendChild(backdrop);
      document.body.style.overflow = "hidden";

      const svg = inner.querySelector("svg");
      if (svg) enableReadout(svg);

      function dismiss() {
        backdrop.remove();
        document.body.style.overflow = "";
        document.removeEventListener("keydown", onKey);
      }
      function onKey(e) {
        if (e.key === "Escape") dismiss();
      }
      backdrop.addEventListener("click", function (e) {
        if (e.target === backdrop) dismiss();
      });
      closeBtn.addEventListener("click", dismiss);
      document.addEventListener("keydown", onKey);
    }

    cards.forEach(function (card) {
      card.addEventListener("click", function () {
        open(card);
      });
      card.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open(card);
        }
      });
    });
  });

  // ---------- Password visibility (same mechanism as fleetbox) ----------
  // Wrap every password field and inject a show/hide toggle. Done from JS so
  // the button only exists when it can work.
  document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const EYE =
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>';
    const EYE_OFF =
      '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><line x1="4" y1="4" x2="20" y2="20"/></svg>';
    const showLabel = body.dataset.pwShow || "Show password";
    const hideLabel = body.dataset.pwHide || "Hide password";

    document.querySelectorAll('input[type="password"]').forEach(function (input) {
      const wrap = document.createElement("span");
      wrap.className = "pw-field";
      input.parentNode.insertBefore(wrap, input);
      wrap.appendChild(input);

      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "pw-toggle";
      toggle.innerHTML = EYE;
      toggle.setAttribute("aria-label", showLabel);
      toggle.title = showLabel;
      wrap.appendChild(toggle);

      toggle.addEventListener("click", function () {
        const makeVisible = input.type === "password";
        input.type = makeVisible ? "text" : "password";
        toggle.innerHTML = makeVisible ? EYE_OFF : EYE;
        toggle.setAttribute("aria-label", makeVisible ? hideLabel : showLabel);
        toggle.title = makeVisible ? hideLabel : showLabel;
        input.focus();
      });
    });
  });
})();
