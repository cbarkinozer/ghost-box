# Ghost-box implementation checklist

Build a small desktop application in reviewable steps. This is a plan, not a list of implemented features. Start with a mostly empty window, then make Gmail usable before adding inference.

## Working rules

- [ ] Keep each increment small, runnable, and easy to read; explain changed files and how to run it.
- [ ] Use Python, PySide6 Qt Widgets, and standard-library SQLite. No web frontend or HTTP application server.
- [ ] Add dependencies only when their benefit outweighs their code and packaging cost; record why each is needed.
- [ ] Prefer direct functions and small modules. Avoid agent frameworks, repositories/services layers, plugin systems, and speculative abstractions.
- [ ] Keep long-running work off the UI thread. Add only tests that validate meaningful behavior.
- [ ] Keep credentials, messages, downloaded weights, and evaluation results containing private data out of Git.

## 1. Mostly empty desktop application

- [x] Add minimal project metadata and one documented launch command.
- [x] Open a single window titled **Ghost-box** with a simple empty state.
- [ ] Reserve a small toolbar for account, date range, Fetch, and settings; add controls as they become functional.
- [ ] Keep the initial layout plain: mail list and content area. Add the question field when inference works.
- [x] Confirm clean startup and shutdown without loading model libraries or starting background services (macOS native-window smoke check).

**Done when:** the user can launch and inspect a mostly empty native window. No Gmail or model implementation in this increment.

## 2. Connect Gmail

- [x] Document Google Cloud desktop OAuth client setup and the required local configuration file.
- [x] Add **Connect Gmail**, account identity, and **Disconnect**.
- [x] Load the application's OAuth configuration automatically; end users only click Connect and sign in with Google.
- [ ] Maintainer: register Ghost-box's Google OAuth client and include `oauth-client.json` in configured builds. Verify live sign-in.
- [x] Use the system browser and read-only Gmail OAuth; never ask for a Gmail password.
- [x] Store tokens in the OS credential store. Explain the chosen OAuth and credential-storage dependencies.
- [ ] Handle cancelled login, expired/revoked credentials, and connection errors visibly.
- [x] Disconnect by removing local credentials; do not silently delete downloaded mail.

Live Google sign-in was confirmed by the user. Startup reads saved identity locally. Fetch now refreshes expired tokens and reports revoked access; fetching still needs the first live mailbox check.

**Done when:** connecting and disconnecting work without downloading messages or starting a model.

## 3. Fetch a date range

Date/time controls default to **today 00:00–23:59**, including the entire end minute. Each successful fetch atomically replaces the connected account's previous local emails; failure or cancellation keeps them. Fetch/cancellation status is shown in the UI; durable fetch coverage/history is still pending.

- [x] Add **From**, **To**, and **Fetch**. Reject reversed or invalid ranges.
- [x] Include editable hours/minutes in local time; the To minute is inclusive, converted to an exclusive next-minute bound.
- [x] Document whether filtering uses Gmail's internal received timestamp; verify boundary behavior.
- [x] Fetch only on button press. Support pagination, progress, cancellation, and useful errors.
- [x] Include Sent; exclude Spam, Trash, and Drafts. Show this scope in the initial reader hint.
- [x] Store Gmail message/thread IDs, sender, recipients, subject, timestamp, and readable body in SQLite.
- [x] Handle plain-text and HTML-only messages without rendering active HTML or fetching remote assets. Defer attachments.
- [x] Replace previous local messages in one transaction after a successful fetch; avoid duplicates and preserve old messages on failure/cancellation.
- [ ] Record successful fetch coverage and partial/cancelled fetch status honestly; no scheduled synchronization.

**Done when:** a selected range produces browsable local messages, a second fetch creates no duplicates, and boundary dates behave as displayed.

## 4. Browse, search, and clear local data

- [x] Show a simple sender/subject/date list and readable selected message; group conversations only as needed for summaries.
- [ ] Add local keyword/exact-text search and sender, subject, and date filters using SQLite/FTS5.
- [ ] Add **Delete local copy** for selected messages. Remove associated index entries and derived results; never delete from Gmail.
- [ ] Explain that a later Fetch can download deleted local messages again; no suppression-list feature initially.
- [ ] Add **Clear cache** for derived summaries/results while keeping downloaded messages, account, and models.
- [ ] Add a separate **Remove all downloaded mail** action that also clears associated derived data.
- [ ] Cancel or invalidate in-flight work when its source data is deleted so stale output cannot repopulate the cache.

**Done when:** search works without a loaded model, deleted mail disappears from retrieval, and cleanup actions have distinct, clear effects.

## 5. Model selection and download

**Next increment after code review:** a small Caspy model-selection side panel. Do not implement until the user resumes.

Initial preset: [mlx-community/Qwen3.5-4B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit).

- [ ] First run a small text-only compatibility check with a pinned MLX runtime. The model card demonstrates mlx-vlm; do not assume the smallest text-only runtime works without checking.
- [ ] Add one model settings panel: preset selector, **Download**, **Choose local model**, and selected-model status.
- [ ] Download the preset to one documented application model directory; pin the revision and validate required artifacts.
- [ ] Show progress, cancellation, retry, and readable disk/network errors. Never treat a partial download as ready.
- [ ] Reuse complete downloaded files and avoid duplicate application/Hub caches where practical.
- [ ] Support a custom MLX directory first; validate compatibility and report unsupported models clearly.
- [ ] Keep downloaded weights separate from mail and derived cache. Offer explicit **Remove downloaded model** without deleting user-owned custom directories.
- [ ] Require explicit selection before using a model; do not download on launch or fall back to a remote service.

**Done when:** a user can download/select the preset or select a compatible local directory, restart the application, and retain that selection.

## 6. Local inference and lifecycle

- [ ] Run inference in a separate on-demand process with a small explicit communication protocol.
- [ ] Show unloaded/loading/ready/generating/error states, streamed output, and **Stop**.
- [ ] Add **Unload model** and a configurable idle timeout. Do not unload during active generation.
- [ ] Unload the previous model before switching and stop the worker on application exit.
- [ ] Add a collapsed **Advanced** section with maximum output tokens, temperature, and idle timeout; provide safe defaults and reset.
- [ ] Validate advanced values. Add context/retrieval limits only if needed; avoid exposing runtime internals by default.
- [ ] Confirm local inference works offline after setup and that model memory is released when the worker exits.

**Done when:** the selected model responds without blocking the UI, generation can stop, and idle unloading works.

## 7. Email assistance: bounded workflows

- [ ] Summarize a selected email with references to the original text.
- [ ] Summarize a conversation chronologically, limiting repeated quoted content and respecting the input budget.
- [ ] Translate natural-language search into a small validated structure: sender/name, recipient, subject, date range, and terms.
- [ ] Display interpreted filters so the user can inspect or correct them. Ask for clarification when names or dates are ambiguous.
- [ ] Execute parameterized local queries in application code; the model never executes SQL, shell commands, or tools.
- [ ] Answer questions from retrieved mail with source references and an explicit no-evidence response when appropriate.
- [ ] Show local search coverage; do not imply the entire Gmail mailbox was searched.

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

- [ ] Record query, expected IDs/facts, model revision, runtime, generation settings, and result.
- [ ] Score retrieval by expected IDs and filter correctness; manually review summaries for omissions and unsupported claims.
- [ ] Record end-to-end latency and peak memory on the actual Mac. Set budgets from measurements.
- [ ] Keep date-range, repeated-fetch, deletion, and cache-clearing checks separate from model quality evaluations.

## 9. Later compatibility and release work

- [ ] Add custom GGUF selection and a bundled llama.cpp worker for macOS/Windows after the MLX path works.
- [ ] Select and validate a Windows preset separately; the MLX preset is Apple-Silicon-only.
- [ ] Add Outlook only after the Gmail workflow is complete.
- [ ] Package native applications and verify startup, idle memory, downloads, credentials, and worker shutdown on supported devices.
- [ ] Review local data protection, retention, backups, dependencies, and network boundaries before broader confidential use.

## Keep deferred

No Docker distribution, separate application SSO, automatic fetching, sending/deleting provider mail, attachments, calendars, notifications, ranking, dashboards, vector database, plugin system, or agent framework. Revisit only when a demonstrated need warrants the additional code.
