# Ghost-box implementation checklist

Build a small desktop application in reviewable steps. Checked items are implemented or backed by the specific validation stated; unchecked items remain pending. Implementation checks do not replace the model-quality benchmark or device-specific release validation. Mixed implementation/release tasks are split below.

## Email retention

- [x] Keep emails and metadata only in RAM; every launch starts empty.
- [x] Clear session mail on disconnect, account change, and application exit.
- [x] Remove legacy email database files at startup; never load them.
- [x] Keep summaries, conversations, and BM25 working data in RAM.
- [x] Track successful fetch coverage in RAM; retain it on cancelled/failed attempts and clear it with all local mail.

## Working rules

Ongoing constraints: checked means the current implementation follows the rule; keep applying it to future changes.

- [x] Keep each increment small, runnable, and easy to read; explain changed files and how to run it.
- [x] Use Python and PySide6 Qt Widgets. Keep email content, metadata, and derived results in RAM only. No web frontend or HTTP application server.
- [x] Add dependencies only when their benefit outweighs their code and packaging cost; record why each is needed.
- [x] Prefer direct functions and small modules. Avoid agent frameworks, repositories/services layers, plugin systems, and speculative abstractions.
- [x] Keep long-running work off the UI thread. Add only tests that validate meaningful behavior.
- [x] Keep credentials, messages, downloaded weights, and evaluation results containing private data out of Git.

## 1. Mostly empty desktop application

- [x] Add minimal project metadata and one documented launch command.
- [x] Open a single window titled **Ghost-box** with a simple empty state.
- [x] Reserve a small toolbar for account, date range, Fetch, and settings; add controls as they become functional.
- [x] Keep the initial layout plain: mail list and content area. Add the question field when inference works.
- [x] Confirm clean startup and shutdown without loading model libraries or starting background services (macOS native-window smoke check).

**Done when:** the user can launch and inspect a mostly empty native window. No Gmail or model implementation in this increment.

## 2. Connect Gmail

- [x] Document Google Cloud desktop OAuth client setup and the required local configuration file.
- [x] Add **Connect Gmail**, account identity, and **Disconnect**.
- [x] Load the application's OAuth configuration automatically; end users only click Connect and sign in with Google.
- [x] Register the Google Desktop OAuth client and verify live Gmail sign-in with the local configuration (confirmed by the user).
- [ ] Include the OAuth configuration in configured distributable builds and verify sign-in on a fresh device; keep it out of Git.
- [x] Use the system browser and read-only Gmail OAuth; never ask for a Gmail password.
- [x] Store tokens in the OS credential store. Explain the chosen OAuth and credential-storage dependencies.
- [x] Handle cancelled login, expired/revoked credentials, and connection errors visibly.
- [x] Disconnect by removing local credentials and clearing session mail.

Live Google sign-in and mailbox fetching were confirmed by the user. Startup reads saved identity locally. Fetch refreshes expired tokens and reports revoked access; safe account/fetch errors are implemented and tested with mocks. Fresh-device and broader live error-path checks remain release work.

**Done when:** connecting and disconnecting work without downloading messages or starting a model.

## 3. Fetch a date range

Date/time controls default to **today 00:00–23:59**, including the entire end minute. Each successful fetch atomically replaces the connected account's previous local emails; failure or cancellation keeps them. Fetch coverage shows the actual successful date/time range, category exclusions, completion time and retained counts. Failed/cancelled attempts keep the previous coverage; editing controls does not rewrite it. Nothing is restored on launch.

- [x] Add **From**, **To**, and **Fetch**. Reject reversed or invalid ranges.
- [x] Include editable hours/minutes in local time; the To minute is inclusive, converted to an exclusive next-minute bound.
- [x] Document whether filtering uses Gmail's internal received timestamp; verify boundary behavior.
- [x] Fetch only on button press. Support pagination, progress, cancellation, and useful errors.
- [x] Include Sent; exclude Spam, Trash, and Drafts. Show this scope in the initial reader hint.
- [x] Store Gmail message/thread IDs, sender, recipients, subject, timestamp, and readable body in session memory only.
- [x] Handle plain-text and HTML-only messages without rendering active HTML or fetching remote assets. Defer attachments.
- [x] Replace previous local messages in one in-memory replacement after a successful fetch; avoid duplicates and preserve old messages on failure/cancellation.
- [x] Keep successful fetch coverage and last-attempt cancelled/failed/in-progress status in RAM; no scheduled synchronization. Answers retain their original coverage snapshot.

**Done when:** a selected range produces browsable local messages, a second fetch creates no duplicates, and boundary dates behave as displayed.

## 4. Browse, search, and clear local data

- [x] Show a simple sender/subject/date list and readable selected message; group conversations only as needed for summaries.
- [x] Add instant case-insensitive literal search over fetched mail, with All text / Sender / Subject / Body scopes and visible-only Select all; no model or disk index.
- [ ] Add a local date filter if needed; the existing From/To controls limit fetching, not the already-fetched inbox view.
- [x] Add **Delete local** for selected visible messages; remove their RAM copies and entire dependent conversations/snapshots. Keep unrelated sessions and never delete from Gmail.
- [x] Explain local-only deletion and later re-fetching in the control tooltip and completion status; no suppression list.
- [x] Add **Clear sessions** to remove RAM-only conversations, summaries, answers, diagnostics, work steps, and retained source snapshots while keeping the fetched inbox, account, and models. There is no disk mail/result cache.
- [x] Add **Clear all mail** to clear the inbox, conversations, retained source snapshots, search/question input and coverage from RAM while keeping account/models.
- [x] Stop source-dependent inference before deletion, ignore late output, and remove dependent sessions. Disable cleanup during account/fetch operations to avoid a replacement-fetch race.

**Done when:** search works without a loaded model, deleted mail disappears from retrieval, and cleanup actions have distinct, clear effects.

## 5. Model selection and download

The Caspy sidebar saves a preset or local-folder selection using Qt settings. The preset downloader verifies pinned files on demand. The pinned preset passed text-only offline generation with optional mlx-lm 0.32.2; selected-email Q&A now runs in an on-demand worker.

- [x] Add a small sidebar with preset/local-folder selection and restore the selection after restart.

Initial preset: [mlx-community/Qwen3.5-4B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit).

- [x] First run a small text-only compatibility check with a pinned MLX runtime. The model card demonstrates mlx-vlm; do not assume the smallest text-only runtime works without checking.
- [x] Add one model settings panel: preset selector, **Download**, **Choose local model**, and selected-model status.
- [x] Download the preset to one documented application model directory; pin the revision and validate required artifacts.
- [x] Show progress, cancellation, retry, and readable disk/network errors. Never treat a partial download as ready.
- [x] Reuse complete downloaded files and avoid duplicate application/Hub caches where practical.
- [x] Select a custom MLX directory or GGUF file, check its path/platform/runtime, and surface load errors without blocking the UI.
- [ ] Broaden custom-model compatibility validation and provide more specific unsupported-model diagnostics beyond the current load-error reporting.
- [x] Keep model weights and numeric settings separate from RAM-only mail and derived results.
- [x] Offer confirmed **Remove preset…** for built-in app-managed files, after unloading the worker. Refuse custom selections, links/reparse points, unknown files and foreign completion records; keep numeric profiles.
- [x] Require explicit selection before using a model; do not download on launch or fall back to a remote service.

**Done when:** a user can download/select the preset or select a compatible local directory, restart the application, and retain that selection.

## 6. Local inference and lifecycle

- [x] Run inference in a separate on-demand process with a small explicit communication protocol.
- [x] Show unloaded/loading/generating/error states, streamed output, and **Stop**; retain the worker while idle and unload after five minutes.
- [x] Add manual Load/Unload and five-minute warm-model idle timeout; pause the timer during generation.
- [x] Unload before model/settings reload and stop the worker on exit; retain only one model.
- [x] Add collapsed inference controls with per-model numeric profiles in local JSON and reviewed preset defaults.
- [x] Add **Reset model defaults** to restore/save shipped defaults for the selected model while preserving other profiles; the warm-worker idle timeout remains fixed at five minutes.
- [x] Validate sampling parameters, input/output budgets, and task caps in both UI and worker.
- [x] Check offline MLX/GGUF warm reuse and request-cache clearing on macOS with synthetic messages.
- [x] Show explicit loaded/unloaded state, worker peak RAM, and MLX allocator memory; distinguish historical measurements.
- [x] Report actual LLM calls separately from tasks; show end-to-end elapsed seconds.
- [x] Show a compact live checklist of operation purposes and source groups, with pending/running/done/failure/stop states; distinguish local steps from LLM-call counts, expose BM25 use/non-use, and retain the checklist/search status in RAM-only message history.
- [x] Raise the Qwen preset output budget to 2,048, migrate old 512 defaults, and mark token-limit cutoffs as partial.
- [x] Show a qualified full-attention KV-cache growth illustration; do not imply an exact total-RAM prediction.

**Done when:** the selected model responds without blocking the UI, generation can stop, and manual/idle unloading releases model memory.

## 7. Email assistance: bounded workflows

- [x] Add RAM-only sessions/messages with selectable history; clear on disconnect/account change/exit and restore nothing on launch.
- [x] Follow up from the displayed previous answer/request, without replaying all source bodies; retain source snapshots for explicit bounded lookup.
- [x] Add a small JSON router: previous answer, one email by ID, or BM25 passages; at most two LLM calls and one local lookup per follow-up.
- [x] Stream short chat answers with a 512-token ceiling; retain the full configured budget for summaries/drafts.
- [x] Supply only top matching excerpts for BM25-assisted Ask emails, not all searched email bodies.
- [x] Add optional model-planned BM25 search restricted to scoped mail; count the extra call and validate the tool schema.
- [x] Add a visible, saved Skip Promotions fetch filter, initially enabled.

- [x] Render completed/partial output as native Qt Markdown; block external navigation and resource loading.
- [x] Link known source citations to email preview without changing selection; support Turkish/English labeled references as well as bracketed numbers.
- [x] Make Follow up discoverable immediately after an answer; an empty-input click focuses the question field and preserves output.
- [x] Add saved response-language preference (Türkçe initially, English available).
- [x] Give answers more space and use native system fonts with readable minimum sizes.
- [x] Organize application code into ui, mail, and models packages; keep main.py as launcher.

- [x] Select multiple emails, select all fetched emails, or clear selection.
- [x] Show input characters and approximate tokens (characters / 4, rounded up).
- [x] Ask one question using only selected emails; stream the answer and support Stop.
- [x] Keep questions and answers in RAM; preserve the answer while browsing or changing next-request options, with its original source snapshot shown.
- [x] Reuse one warm worker between answers; clear request caches and unload manually or after five idle minutes.

- [x] Add Summarize for selected emails with optional RAM-only instructions.
- [x] Batch emails by input/output budget; validate keyed records and exact source quotations.
- [x] Render batch cards incrementally and assemble a source-bound overview locally; order by estimated request type, observed To/CC role, and source order without another LLM call.
- [x] Use flat summary records selecting numbered original evidence passages; omit URL tokens from summary context, retain valid neighboring records, and retry only missing/invalid/empty findings once within budget.
- [x] Give answers and work steps full-area tabs, put the question field below output, fold email preview during inference, and make the model sidebar optional. Click failed steps for RAM-only failure details.
- [x] Add RAM-only, per-message summary diagnostics: fixed rejection/classification/retry codes, source ordinals, call counts, input-token counts, output-character counts, and call timings; cap records and allow explicit content-free copying without a log file.
- [x] Test that diagnostic events/reports exclude mail content, identifiers, prompts and raw model output; preserve diagnostics across message navigation and clear with sessions.
- [x] Show real recipient role/counts, CC, timestamp, and attachment count separately from model-estimated mail type.
- [x] Add source-bound Reply / Reply all / Forward with editable RAM-only drafts.
- [x] Add one-level **Undo Caspy rewrite**, preserving the exact pre-generation text in RAM, including failed/interrupted rewrites; disable undo while generating/sending and clear the backup on dialog close.
- [x] Add opt-in Gmail send permission, recipient/body confirmation, threaded replies, and no ambiguous automatic retry.
- [ ] Verify live Gmail send authorization/delivery manually; automated checks use mocks only.
- [ ] Add attachment forwarding and voice input in later increments.
- [x] Split oversized selections into token-budgeted evidence tasks and hierarchical synthesis; show created/completed counts and enforce a call limit.
- [ ] Evaluate summary omissions, source references, and conflicts across batch boundaries.
- [ ] Summarize a conversation chronologically, limiting repeated quoted content and respecting the input budget.
- [ ] Translate natural-language search into a small validated structure: sender/name, recipient, subject, date range, and terms.
- [ ] Display interpreted filters so the user can inspect or correct them. Ask for clarification when names or dates are ambiguous.
- [x] Run validated BM25 queries and ID-scoped mail lookups in application code; never execute model-supplied SQL, shell commands, or arbitrary tools. Natural-language metadata filtering remains pending above.
- [x] Answer from retrieved mail excerpts with source-link rendering and explicit no-evidence instructions. Verify factual accuracy and correct refusal behavior through the pending evaluation set.
- [x] Show selected source scope, BM25 query/match counts, and explicit search use/non-use for the current request; retain that status in RAM-only message history.
- [x] Show fetched date-range coverage, exclusions and completion time in the inbox, and retain original answer coverage in its header tooltip; explicitly limit scope to fetched/selected mail.

**Done when:** the evaluation cases below can be reviewed against exact source messages. No agent loop or embeddings.

## 8. Small evaluation set

Start with approximately 20–30 synthetic messages across a few threads and 10 cases. Keep fixtures and expected results in simple JSON files, with a small runner using existing dependencies. Add private user-selected examples locally later; never commit real mailbox content.

| # | Task | Expected evidence |
| --- | --- | --- |
| 1 | Find mail from a person's name | Correct message IDs; clarify two people with the same display name |
| 2 | Find an exact subject phrase or identifier | Correct matching IDs without unrelated results |
| 3 | Apply sender and inclusive date boundaries | Expected filter structure and exact matching IDs |
| 4 | Combine recipient, subject, and date in natural language | Validated filters and expected local results |
| 5 | Summarize one email | Required facts retained; names, amounts, and dates unchanged |
| 6 | Summarize a thread with a revised decision | Latest decision distinguished from earlier proposals |
| 7 | Extract a stated request and deadline | Source-supported action/date; no invented deadline |
| 8 | Answer a question across several messages | Correct answer with supporting message IDs/passages |
| 9 | Answer an unsupported question | Explicit lack of evidence; downloaded scope acknowledged |
| 10 | Handle Turkish/English text and malicious instructions inside mail | Correct retrieval; content cannot grant authority or justify unsupported claims |

- [ ] Record query, expected IDs/facts, model revision, runtime, generation settings, result, and structured diagnostic codes in synthetic benchmark runs. Never persist private-mail traces.
- [ ] Score retrieval by expected IDs and filter correctness; manually review summaries for omissions and unsupported claims.
- [x] Measure/display end-to-end elapsed time, actual model-call counts, worker peak RAM, and MLX allocator memory on macOS; synthetic checks and user-run MLX/GGUF trials exist.
- [ ] Record repeatable benchmark latency/memory results and establish budgets from those measurements; ad hoc timings are not the comparison benchmark.
- [x] Keep date-boundary, repeated-fetch, RAM-retention, and conversation-clearing regression tests separate from model quality evaluations.
- [x] Add separate deletion/all-mail cleanup, stale-output invalidation, coverage preservation, draft undo, profile reset, and safe preset-removal checks using synthetic mail and temporary model fixtures.

### Repeatable model comparison benchmark

- [ ] Add a small CLI benchmark runner using the same versioned synthetic fixtures, expected answers, and prompt/workflow versions for every candidate model; support local MLX and GGUF without another framework.
- [ ] Track accuracy per case: retrieval IDs, required facts, unsupported claims, source attribution, dates/amounts/statuses, selected response language, appropriate no-evidence answers, and follow-up lookup decisions. Keep human factual review separate from deterministic checks; language compliance alone is not factual accuracy.
- [ ] Record end-to-end latency, time to first visible answer token (including routing/retrieval), model load time, and actual LLM-call count. Measure cold and warm runs separately; include failures/timeouts and run counts in reports.
- [ ] Track actual input/output token counts and generation throughput (tokens/s) per LLM call, with the tokenizer/runtime identified. Define decode tokens/s from generated tokens and measured decode duration; report prompt/prefill throughput separately when available. Do not substitute characters/4, words/s, or output tokens divided by full workflow latency for decode tokens/s; mark unavailable runtime metrics explicitly.
- [ ] Record model ID/revision, quantization, runtime/version, inference parameters/seed where supported, device/OS, and peak RAM so comparisons are reproducible. Repeat cases and report accuracy plus median/tail latency and throughput with sample counts.
- [ ] Produce simple JSON results and a Markdown comparison table against the current baseline before changing the preset. Choose on accuracy and acceptable latency/memory together, not speed alone. Use only synthetic fixtures in committed reports; keep private-mail evaluation inputs/results out of Git.

## 9. Later compatibility and release work

- [x] Add local GGUF selection and optional pinned llama.cpp Python backend; smoke-test on macOS.
- [ ] Bundle the llama.cpp runtime in packaged Windows builds and validate DLL loading on a fresh device without a compiler. Native Windows source-run validation remains a separate item below.
- [x] Add a pinned, SHA-256-verified Qwen3.5 GGUF Q4_K_M download preset beside MLX; preserve independent selection/settings and custom model paths.
- [x] Include the pinned upstream Windows x64 CPU llama.cpp wheel in the base `uv run --locked main.py` environment; verify Windows dependency resolution without changing the macOS extras.
- [ ] Validate the selected GGUF preset on real Windows hardware; macOS cross-platform resolution is not native Windows validation.
- [ ] Add Outlook only after the Gmail workflow is complete.
- [ ] Package native applications and verify startup, idle memory, downloads, credentials, and worker shutdown on supported devices.
- [ ] Review local data protection, retention, backups, dependencies, and network boundaries before broader confidential use.

## Future optimizations

- [ ] Evaluate a small local spam/attention decision model; optionally gray out low-attention mail while keeping it selectable and available. No automatic removal or provider-side action.
- [ ] Later add a natural-language fetch description next to From/To: people, date ranges, or keywords. Translate intent to validated visible filters before a user-triggered Fetch; do not implement yet.
- [ ] Consider additional bounded read-only tools after BM25, only for demonstrated needs; no general agent framework.
- [ ] Consider explicit Social/Updates category controls after the current Promotions option; do not silently hide categories.

## Keep deferred

No Docker distribution, separate application SSO, automatic fetching, automatic sending/deleting provider mail, attachment-content processing, calendars, notifications, ranking, dashboards, vector database, plugin system, or agent framework. Revisit only when a demonstrated need warrants the additional code.


## Current increment validation

- [x] Historical synthetic check: 20 emails/20 quote-checked cards in five calls; this preceded removal of the overview LLM call.
- [x] Regression test: overview ordering uses existing findings only and cannot call a model or fail JSON parsing.
- [x] Current synthetic MLX check: 10 emails yielded 10 source-checked summary records in two extraction calls (15.8 seconds on this Mac); local overview added no model call. This does not establish semantic accuracy.
- [x] Native Cocoa diagnostics/details dialog smoke check; OS TSM messages still reproduced, without a crash in that check.
- [ ] Investigate the reproduced macOS TSM native diagnostic; asynchronous read-only dialogs are implemented but are not a confirmed fix. Do not hide stderr.
- [x] Local Turkish reply drafting without a send grant or delivery.
- [x] Mocked send tests: canceled approval makes no call, approved payload stays frozen, success prevents duplicate submission, ambiguous failure is not retried.
- [ ] Broader summary accuracy, adversarial mail, real Gmail delivery, and native Windows checks remain required before broad use.
