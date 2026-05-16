from __future__ import annotations

import streamlit as st


def inject_browser_storage_sanitizer(*, enabled: bool = True) -> None:
    """Best-effort mitigation for browser JSON.parse console errors."""

    if not enabled:
        return

    # Streamlit 1.56+ supports inline HTML with JavaScript via st.html.
    # Keeping this script inline lets it sanitize same-origin browser storage
    # without relying on the deprecated components.v1 HTML iframe helper.
    st.html(
        """
        <div style="display:none"></div>
        <script>
        (function () {
          function previewValue(value) {
            if (value === null || value === undefined) return String(value);
            const text = String(value);
            return text.length > 100 ? (text.slice(0, 100) + "...") : text;
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
            if (first === "{" || first === "[" || first === '"') return true;
            if (s === "null" || s === "true" || s === "false") return true;
            // JSON numbers (including exponent) or strings that begin like numbers.
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

              // Looks JSON-like but cannot be parsed, so remove it to avoid downstream crashes.
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
        width="content",
        unsafe_allow_javascript=True,
    )
