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
})();
