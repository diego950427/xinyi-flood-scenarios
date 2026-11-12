# Cloud app review — 2026-11-12

Scope: read-only inspection of `app.py`, `backend.py`, `worker.py`, `cloud_runtime.py` and the native progress/cancellation code. This is not a new native solver run or a claim of Linux E2E success.

## Finding

**P2 — Another visitor's finished job does not re-enable the waiting visitor's start button automatically.** In `app.py`, `current_job` determines the disabled button during the full script run. A visitor with no own `monitored_run` gets `rid=None` in `progress_panel()` and returns immediately. The fragment continues polling, but when the shared worker becomes idle there is no full rerun to refresh the disabled button. The visitor must change another widget or reload. Recommended fix: detect the shared busy-to-idle transition in the fragment and trigger a full rerun; do not show the other visitor's run ID or results. This finding was established by control-flow review, not a browser E2E reproduction.

## Checks and boundaries

- Each browser session creates a random owner token; the stored owner is its SHA-256. `visible_runs()` filters by owner and `cancel_job()` checks owner before writing any cancellation flag. The UI result selector is built only from that filtered list plus public examples. No route exposing arbitrary run paths was found in these files.
- Run IDs reject path separators and traversal strings. Native commands use argument arrays, not a shell. Result archive member paths are relative to the selected result folder.
- Public examples are loaded read-only by the app and explicitly labelled as precomputed Windows V2 results. Their numerical files remain byte-identical to V2. Portable QGIS presentation files are separately declared as regenerated.
- Native completion is not inferred from a zero exit alone: output clocks, finite state, rain integral, balances, storage and warnings are checked before `completed`. Failed checks become `failed_qa`; exceptions become `failed`. There is no mocked successful fallback.
- Native progress contains only time/end/step fields, so merging it into status does not overwrite the failure/completion state. Worker liveness checks use PID plus process creation time.
- Cancellation is cooperative during the native loop. It is queued during native-runtime preparation; it does not immediately abort a build. A forcibly killed worker could leave its native child alive until that child's two-hour safeguard; this is an operational boundary, not a demonstrated normal-flow failure.
- Two current example ZIPs were actually opened and CRC-checked: 26 members each, no ZIP traversal members, no personal Windows path or obvious credential match in text entries. This bounded scan is not a proof that every possible secret format is absent.
- `qa/data_release_audit.py` was actually rerun after manifest classification: all 10 checks passed. Original numerical SHA values were checked directly, separately from regenerated QGIS/README hashes.

The application review found no critical cross-session cancellation/listing issue in the current UI flow. Linux CI/native E2E and deployed-host behavior remain separate acceptance checks.
