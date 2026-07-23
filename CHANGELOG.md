# Changelog

## v2.8.5rc13 - 2026-07-23

- hardened ClamD scan-content consistency by calculating SHA-256 from the exact bounded INSTREAM chunks and reconciling pre/post file identity
- added conservative ClamScan fallback stability checks before clean results can become reusable cache entries
- split folder malware caching into unchanged-file and content-hash lookup stages with engine-version compatibility
- corrected `mode_excluded` semantics so mode exclusions are partial coverage evidence, not completed scanner results
- preserved enumeration boundary safety while exposing in-scope, completed, incomplete, and mode-excluded counts distinctly
- kept scanner metrics tied to actual scanner work and unchanged-file cache skips
- removed the inner `.block-container` page scroll surface for a stable single-scroll viewport layout
- preserved duplicate-group identity stability and finalized release documentation for the rc13 stabilization pass

## v2.8.5rc12 - 2026-07-22

- switched `clamd` file scans to true streamed `INSTREAM` uploads instead of whole-file `read_bytes()` loads
- integrated the persistent malware cache into folder malware scans and surfaced exact cache-hit accounting
- separated scan-mode exclusions from genuine malware scan failures and incomplete backend results
- fixed recursive folder enumeration completeness, explicit limit-reached tracking, and max-file boundary warnings
- made malware scan progress, completion counts, and throughput metrics reflect exact scanner work
- stabilized the home page desktop shell as a single-scroll `100dvh` layout
- saved per-result analysis setting snapshots for stable report and dialog rendering
- added stable duplicate-group identifiers that do not depend on display text

## v2.8.5rc11 - 2026-07-21

- repaired damaged Traditional Chinese malware-result and dialog translations
- centralized malware scan-result severity and conclusion handling
- corrected batched ClamAV timeout semantics to honor per-file timeout budgets
- removed the remaining per-file ClamAV scan path from batch helpers
- clarified incomplete, partial-coverage, and missing-result explanations
- added regression tests for locale quality, malware result severity, and batch scanner behavior
