from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as st_components


def inject_browser_storage_sanitizer(*, enabled: bool = True) -> None:
    """Best-effort mitigation for local Streamlit browser-storage JSON.parse errors.

    This inline script only cleans same-origin `localStorage` and `sessionStorage`
    values created by the local Streamlit UI state layer. It does not process
    external user HTML, does not accept arbitrary JavaScript input, and is not a
    general-purpose HTML injection channel.
    """

    if not enabled:
        return

    # Streamlit 1.56+ supports inline HTML with JavaScript via st.html.
    # Keeping this script inline limits scope to local UI-state cleanup without
    # adding remote scripts, CDN dependencies, or broader browser privileges.
    body = """
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
        """
    try:
        st.html(
            body,
            width="content",
            unsafe_allow_javascript=True,
        )
    except TypeError:
        st_components.html(body, height=0, width=0)
