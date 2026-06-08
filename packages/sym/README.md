# packages/sym — reserved fold-in slot

Intentionally empty. QRP consumes the existing **sym** warehouse (at `C:\Projects\sym`)
as a separate repo for now. When sym folds into this monorepo, it moves here via `git mv`
(history preserved) and becomes a uv workspace member — a mechanical move, not a re-layout.

Until then: the API reads sym's database via views and (for Q3 ops) imports sym
library-first. See `_bmad-output/planning-artifacts/architecture-qrp.md` (in the sym repo).
