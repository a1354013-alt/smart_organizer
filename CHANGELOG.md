# Changelog

## v2.8.5rc11 - 2026-07-21

- repaired damaged Traditional Chinese malware-result and dialog translations
- centralized malware scan-result severity and conclusion handling
- corrected batched ClamAV timeout semantics to honor per-file timeout budgets
- removed the remaining per-file ClamAV scan path from batch helpers
- clarified incomplete, partial-coverage, and missing-result explanations
- added regression tests for locale quality, malware result severity, and batch scanner behavior
