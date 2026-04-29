from __future__ import annotations

import streamlit as st


def inject_browser_storage_sanitizer(*, enabled: bool = True) -> None:
    """Best-effort mitigation for browser JSON.parse console errors.

    Streamlit's frontend (and some libraries) persist UI state in Web Storage.
    If a key that is expected to be JSON contains a non-JSON string (e.g. "v2.8.4",
    "", "undefined", or a corrupted number like "1e+"), the browser console may
    show JSON.parse errors and some UI code can break.

    We can't change Streamlit's internal JSON.parse calls, but we *can* sanitize
    storage values early in the app render via an embedded script that:
      - wraps JSON.parse in safeParse (never throws)
      - removes obviously-corrupted JSON-like values
      - avoids touching plain strings that don't look like JSON
    """

    if not enabled:
        return

    # Use components.html so the JS executes; markdown sanitization would strip scripts.
    # The iframe is served from the same origin as the Streamlit app, so it can
    # access localStorage/sessionStorage for that origin.
    st.components.v1.html(
        """
        <script>
        (function () {
          function previewValue(value) {
            if (value === null || value === undefined) return String(value);
            const text = String(value);
            return text.length > 100 ? (text.slice(0, 100) + "…") : text;
          }

          function safeParse(value, key, storageName) {
            if (value === null || value === undefined) return null;
            const text = String(value);
            if (text.trim() === "") return null;
            try {
              return JSON.parse(text);
            } catch (err) {
              try {
                console.warn(
                  "[smart_organizer] safeParse failed",
                  { storage: storageName, key: key, valuePreview: previewValue(text), error: String(err) }
                );
              } catch (_) {}
              return null;
            }
          }

          function looksJsonLike(text) {
            const s = String(text).trim();
            if (s === "") return false;
            const first = s[0];
            if (first === "{" || first === "[" || first === "\"") return true;
            if (s === "null" || s === "true" || s === "false") return true;
            // JSON numbers (incl. exponent) OR things that start like numbers (so corrupted ones get caught)
            return /^[+-]?(?:\\d+(?:\\.\\d*)?|\\.\\d+)(?:[eE][+-]?\\d+)?$/.test(s) || /^[+-]?\\d/.test(s);
          }

          function sanitizeStorage(storage, storageName) {
            if (!storage) return;
            const keys = [];
            for (let i = 0; i < storage.length; i++) {
              const k = storage.key(i);
              if (k) keys.push(k);
            }

            for (const key of keys) {
              let raw;
              try {
                raw = storage.getItem(key);
              } catch (_) {
                continue;
              }
              if (raw === null || raw === undefined) continue;
              const text = String(raw);
              if (text.trim() === "") continue;

              if (!looksJsonLike(text)) continue;

              const parsed = safeParse(text, key, storageName);
              if (parsed !== null) continue;

              // Looks JSON-like but can't be parsed => corrupted JSON string. Remove to avoid downstream crashes.
              try {
                storage.removeItem(key);
                try {
                  console.warn(
                    "[smart_organizer] removed corrupted JSON-like storage value",
                    { storage: storageName, key: key, valuePreview: previewValue(text) }
                  );
                } catch (_) {}
              } catch (_) {}
            }
          }

          try { sanitizeStorage(window.localStorage, "localStorage"); } catch (_) {}
          try { sanitizeStorage(window.sessionStorage, "sessionStorage"); } catch (_) {}
        })();
        </script>
        """,
        height=0,
        width=0,
    )

