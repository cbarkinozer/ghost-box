# ghost-box

![Caspy](assets/caspy.png)

Caspy has a small model-selection sidebar. Select the Qwen3.5 MLX preset and click **Download preset**, or choose a local MLX folder. Selection persists in Qt settings. Downloading does not load a model. Optional MLX and llama.cpp inference answer questions and summarize explicitly selected emails in a separate process, with bounded batching for large selections.

A lightweight desktop email assistant powered by **Caspy**, your local small language model companion, with on-device inference via MLX and llama.cpp.

Ghost-box helps you summarize email conversations, search downloaded messages, and ask questions with references to the original mail. It is designed for macOS and Windows, with a small Python codebase that is straightforward to read, review, and maintain.

> **Status: local Q&A and summarization.** Gmail fetch/reading, RAM-only emails, model downloads/selection, MLX and local GGUF inference, batch-task progress, memory reporting, and JSON generation profiles are implemented. Synthetic offline and UI checks passed on Apple Silicon. Search, cleanup controls, broader quality evaluations, Windows validation, and packaging remain planned.

## Purpose

Reduce the time spent reading and finding email while keeping AI processing on the user's device. The first release should complete one useful workflow:

1. Connect a mail account.
2. Click **Fetch** to download messages within a selected date range.
3. Open a message or conversation and request a summary.
4. Search downloaded mail or ask a question.
5. Follow the answer's references back to the supporting messages.
6. Reuse a loaded model for follow-ups; unload manually or let the five-minute idle timer release it.

## Design principles

- **Small enough to understand.** Prefer explicit application code, few dependencies, and a narrow feature set.
- **Local AI processing.** Run inference and search on the device. Do not send mail content to a hosted model.
- **User-controlled fetching.** Retrieve mail only when requested; no background mailbox synchronization in the first release.
- **Read-only access.** Read mail without sending, deleting, modifying, or marking messages as read.
- **Responsive by default.** Keep mail fetching, downloads, indexing, and inference off the UI thread.
- **Resource-aware operation.** Start the model when needed and release its process after an idle timeout.
- **Verifiable answers.** Show supporting messages and make incomplete search coverage visible.

## Initial scope

| Area | Planned behavior |
| --- | --- |
| Platforms | macOS on Apple Silicon and Windows; inference support depends on the selected backend and hardware |
| Interface | One desktop window with a mail list, message view, and summary/question panel |
| Accounts | One account initially; Gmail and Outlook connectors introduced in stages |
| Fetching | Manual fetch with a selected date range and visible progress, cancellation, and errors |
| Summaries | Summarize a selected message or conversation, preserving decisions, requests, and stated deadlines |
| Search | Local keyword and exact-text search, with sender, date, and subject filters |
| Questions | Answer from retrieved messages and reference the supporting source text |
| Models | A tested default model download and an option to select an existing local model |
| Storage | RAM-only email and derived results; no email database or disk cache |
| Cleanup | Remove downloaded mail and derived local data through an explicit user action |

The application must distinguish **no supporting message found** from **no such message exists**. Answers should state the relevant local search coverage, including the downloaded date range and the last successful fetch.

## Proposed implementation

The starting stack is **Python and PySide6 (Qt Widgets)**. A simple desktop interface avoids the need for a browser engine, JavaScript frontend, or local web server.

| Component | Responsibility |
| --- | --- |
| PySide6 interface | Display messages, accept questions, and show operation and model status |
| Python application core | Coordinate fetching, storage, retrieval, and inference |
| Python in-memory store | Hold fetched mail only for the current session |
| Mail connectors | Authenticate with the provider and retrieve messages through read-only APIs |
| Model worker | Load a local model and stream generated output in a separate process |

Mail fetching and model downloads run in background workers. Inference runs in a separate process so the UI remains responsive and the application can release model memory by stopping the worker. Keep communication between the application and worker small and explicit.

Python is the initial implementation choice. Introduce another application language only if measurements reveal a concrete limitation. Measure packaged application size, idle memory, and model memory separately.

### Inference backends

| Backend | Platform | Model input |
| --- | --- | --- |
| MLX | macOS on Apple Silicon | Compatible local MLX model directory |
| llama.cpp | macOS and Windows | Compatible local GGUF file |

The user selects the backend explicitly. A file format alone does not establish model compatibility. Complete one backend first, then add the second behind the same narrow inference interface.

The initial model preset is [mlx-community/Qwen3.5-4B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit). Text-only generation was verified with the pinned `mlx-lm==0.32.2` runtime and this preset revision. [Occam](https://huggingface.co/cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora), a Turkish concise-response LoRA, is an additional candidate after conversion and task-specific evaluation. Caspy is the companion's name; the underlying model can change.

Choose the default using email summarization and question-answering results, including factual faithfulness, retrieval quality, latency, and memory usage. Concise output alone is insufficient.

### Model lifecycle

Expose a small set of understandable states: **not configured**, **downloading**, **unloaded**, **loading**, **ready**, **generating**, and **error**.

- Show download progress and support cancellation and retry.
- Validate the configured model before starting inference.
- Load on the first inference request, independently of mail fetching.
- Keep one model worker warm between requests; unload manually or after five idle minutes.
- Never unload during an active generation; let the user cancel it first.
- Surface failures without freezing the interface or repeatedly restarting the worker.

## Retrieval and answers

Use a bounded, predictable workflow:

```text
Question → validated filters → local search → selected source messages → answer with references
```

Begin with in-memory text search and metadata filters. Do not introduce an embedding model or vector service until actual retrieval failures justify the additional complexity. The model must not execute SQL, shell commands, or arbitrary tools.

Handle conversation structure, repeated quoted replies, and message dates explicitly. Evaluate Turkish characters, mixed Turkish/English mail, conflicting statements, and questions that cannot be answered from the downloaded messages.

## Privacy and access boundaries

**Local inference does not mean an entirely offline application.** Connecting an account and fetching messages require communication with Gmail or Microsoft. Model downloads also require network access. The intended boundary is that email content and inference inputs are not uploaded to an AI service.

The initial implementation should:

- Use provider OAuth with read-only mail scopes; avoid collecting mailbox passwords.
- Store account tokens in the operating system's credential store.
- Keep credentials out of the model worker and provide only the messages needed for a request.
- Process email as text without loading remote images, tracking pixels, or active HTML.
- Exclude message bodies, prompts, and answers from routine logs.
- Include no analytics or automatic content-bearing crash uploads.
- Pin model artifacts and dependencies, and verify downloaded model files against the release's expected hashes.
- Treat summaries, search indexes, and saved conversations as sensitive local data.

Manual fetching limits application behavior; it does not reduce the OAuth permissions granted by the provider. Provider registration, consent requirements, and organizational policies must be confirmed before a connected pilot.

Email content is untrusted input. It must not grant permissions or trigger actions. Read-only operation reduces the consequences of prompt injection, but misleading summaries and answers remain possible and require evaluation.

Additional application SSO is deferred unless an organizational requirement calls for it. The initial access assumption is the user's secured operating-system session. Database encryption, backup behavior, retention rules, and OS-enforced process/network restrictions require explicit decisions before broader confidential use; they must not be implied by the word "local."

Native desktop packages are the intended distribution format. Docker is not required for the initial application and is not a substitute for defined security boundaries.

## Delivery plan

The implementation checklist is maintained in [TODO.md](TODO.md). Build one small, runnable increment at a time so every code change can be read and understood before expanding the application.

1. Open a mostly empty desktop window.
2. Connect Gmail and manually fetch a selected date range.
3. Browse, search, and remove local mail; clear derived cache.
4. Download or select a model and manage its lifecycle.
5. Add summaries and natural-language retrieval with a small evaluation set.
6. Add Windows inference support and Outlook after the Gmail/MLX workflow works.

## Acceptance criteria

- The interface stays responsive during fetching, downloading, searching, and inference.
- No mailbox operation occurs without a user-requested fetch or connection action.
- Mail access cannot send or modify messages.
- Answers link to supporting downloaded messages; unsupported answers acknowledge missing evidence.
- The model worker exits after the idle timeout and releases its process-held memory.
- Local search remains available while the model is unloaded.
- Network inspection confirms that inference does not upload message content.
- Cleaning downloaded data removes messages and their application-managed derived data; it does not claim secure erasure of OS backups or storage media.

Record idle application memory, peak model memory, cold-start time, time to first output, and complete task latency on representative devices. Set performance budgets from those measurements before expanding scope.

## Out of scope for the first release

- General-purpose agents, tool execution, or plugin systems.
- Sending mail, modifying folders, or writing labels.
- Automatic prioritization, background synchronization, and notifications.
- Calendar integrations and attachment processing.
- Embeddings, vector databases, or hosted inference fallbacks.
- Extensive theming, dashboards, or a separate application login.

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run from the repository directory:

```sh
uv run --locked main.py
```

uv creates the local `.venv` and installs the locked dependencies on first launch. Python 3.11 or newer is required; uv can provision a compatible interpreter.

The launcher is [main.py](main.py); the desktop interface is in [window.py](ghost_box/ui/window.py). The UI dependency in [pyproject.toml](pyproject.toml) is **PySide6-Essentials**, which provides Qt Widgets without the additional PySide6 Addons package. Its required binding library, shiboken6, is installed transitively. [uv.lock](uv.lock) records exact dependency versions.

PySide6-Essentials remains pinned to the checked version, 6.10.2. A recurring Cocoa discovery error on the development Mac was traced to macOS hidden flags on installed plugin files; changing Qt versions alone did not fix that underlying cause. Before creating the application, `prepare_qt_plugins()` clears only the hidden flag within the installed Qt plugin directory on macOS, preserving other file flags. This handles the condition on each launch without a manual repair command or additional dependency. The source of the recurring hidden flags has not been identified.

The account toolbar is implemented in [window.py](ghost_box/ui/window.py); [gmail.py](ghost_box/mail/gmail.py) handles OAuth and native credential storage. Two additional direct dependencies are `google-auth-oauthlib` for Google's browser-based OAuth with PKCE, and `keyring` for macOS Keychain / Windows Credential Manager. Their transitive dependencies are recorded in the lockfile. The full Gmail API SDK is not installed.

### Connect Gmail

For users, the flow is **Connect Gmail → Google sign-in → consent → connected**. There is no file picker or Google Cloud setup for end users.

The following setup is performed once by the application maintainer:

1. Create or select a project in [Google Cloud Console](https://console.cloud.google.com/) and enable **Gmail API**.
2. Configure the Google Auth Platform consent screen. Choose Internal only if the project and users belong to the appropriate Workspace organization; otherwise use External and add your account as a test user while testing.
3. Add the read-only scope `https://www.googleapis.com/auth/gmail.readonly` to the application's data access configuration.
4. Create an OAuth client with application type **Desktop app**, then download its JSON file. A Web application client is not interchangeable.
5. Save the downloaded configuration as `oauth-client.json` beside the root `main.py` launcher. This filename is ignored by Git. Include the configuration in distributed builds; do not include user tokens. The configuration remains local and untracked.
6. Launch Ghost-box, click **Connect Gmail**, and finish sign-in and consent in the system browser. The application checks the Gmail profile and saves credentials in the OS credential store. No email messages are downloaded.

The official flow uses a temporary loopback callback listener on `127.0.0.1`, not an application web server. Browser authorization waits up to 60 seconds; network requests have 20-second timeouts. If you abandon sign-in, wait for it to time out before retrying. Closing the application is deferred while an account operation is running.

On startup, the application reads only the locally saved account identity; it does not contact Google or assert that saved credentials remain valid. **Disconnect** removes the local credential entry and clears session mail without modifying Gmail or revoking Google's server-side grant. To revoke that grant as well, remove Ghost-box from your Google Account's connected applications.

Google testing restrictions, restricted-scope verification, and Workspace administrator policies can affect sign-in. See [Google's desktop OAuth documentation](https://developers.google.com/identity/protocols/oauth2/native-app). There is no plaintext-token fallback if the native credential store is unavailable.

### Fetch and read mail

**From** defaults to today at **00:00** and **To** to today at **23:59**. Both include editable hours and minutes. Times follow this computer's local timezone, and the entire displayed To minute is included (for example, 10:45 includes messages through 10:45:59.999). Filtering uses Gmail's `internalDate`, with epoch-second queries and an exact millisecond boundary check; it does not rely on the email's Date header. See [Google's timezone guidance](https://developers.google.com/workspace/gmail/api/guides/filtering).

Sent mail is included; Spam, Trash, and Drafts are excluded. **Skip Promotions** starts enabled and adds Gmail’s `-category:promotions` filter; uncheck it before Fetch to include that category. The choice is saved in Qt settings. Other categories remain included. **Cancel** stops between network requests and discards the incomplete replacement. Each successful Fetch replaces the connected account's previous local messages with the new results, including clearing them when the result is empty. The pending result is built in RAM: failure or cancellation preserves the previous session emails, while success replaces the set in memory. No requests are made to mark mail as read or modify Gmail.

Select a row to read the message as plain text. HTML-only mail is converted to text without rendering HTML, loading images, or following links. This initial implementation downloads raw MIME, so attachment bytes may be transferred as part of a message, but attachments are not separately extracted, stored, or displayed.

Messages and metadata are held only in process memory. Every launch starts with an empty mail list; only Fetch retrieves mail. Closing the application, disconnecting, or changing accounts clears session mail. Ghost-box does not write email content or derived results to files, databases, or logs. Earlier versions' `mail.sqlite3` and SQLite sidecar files are removed at startup without loading their contents. Removing those files is ordinary deletion, not a guarantee of erasure from backups or storage snapshots. OS swap and crash dumps are outside this application-level RAM-only guarantee.

OAuth credentials remain in the OS credential store, and model selection remains in Qt settings. Model files and numeric inference profiles are saved to disk; email content, questions, summary instructions, and intermediate notes stay in RAM.

New files for this step are [store.py](ghost_box/mail/store.py) (session-only in-memory storage) and [text.py](ghost_box/mail/text.py) (MIME-to-text conversion); fetching is in [gmail.py](ghost_box/mail/gmail.py), and the UI is in [window.py](ghost_box/ui/window.py). No new dependencies were added.

Run the checks without Google access or real credentials:

```sh
uv run --locked python -m unittest discover -s tests -v
```

### Model downloads

**Download preset** retrieves only the selected public preset from Hugging Face. No mail is included in model-download requests. The approximately 3.1 GB download is pinned to revision `32f3e8ecf65426fc3306969496342d504bfa13f3`; file sizes and SHA-256/Git blob hashes are recorded in `ghost_box/models/data/model_manifest.json`. Files are verified before promotion from `.part` files; completion is recorded only after every file succeeds. Startup checks the completion record and sizes, not full weight hashes; retrying rechecks hashes.

Models live under Qt's application-data directory at `models/<revision>/` (`~/Library/Application Support/Ghost-box/models/` on macOS). This is separate from session-only emails. There is no duplicate Hub cache. Cancel removes the current partial file; verified completed files are reused on retry. Transfers interrupted within one file restart that file. Closing during a download requests cancellation; close again after it stops. Network reads have 20-second timeouts.

The preset's [model card](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit) uses `mlx-vlm`. A downloaded model is not proof of runtime compatibility. Local folders are never modified; compatible MLX models can be used for inference, while unsupported models report an error. Explicit model removal remains a future increment.


### Ask selected emails

On Apple Silicon macOS, install the optional runtime and launch with:

```sh
uv run --locked --extra inference main.py
```

The base launch remains available without inference dependencies. The `inference` extra pins `mlx-lm==0.32.2`, using text-only MLX support rather than a vision runtime; transitive versions are locked in `uv.lock`. Importing MLX happens only inside the on-demand worker, never at UI startup.

Fetch mail, then use Cmd/Ctrl-click or Shift-click to select messages, or **Select all** to include every fetched message. Type a question and press **Ask emails**. Only selected emails' IDs, timestamps, headers, and bodies enter the request. Known source citations, including `[2]`, `[Kaynak: 2]`, `kaynak:2`, and common Source/Kaynak label variants, become numbered links; clicking one opens that email in the preview without changing the selection for the next question. Hovering shows its subject and sender. Unknown references and external/file URLs do not navigate. Markdown rendering disables raw HTML and blocks resource loading, including local and remote images. Unselected emails and previous answers are not included. Each request has an explicit email scope. Use Follow up to include the previous answer and request as context; a warm runtime alone does not retain conversational intent.

The input counter includes the selected message representation, question, and system instructions. Approximate tokens are characters divided by four, rounded up; actual tokenization varies by language. Chat-template overhead is not included in that estimate. The worker measures fully templated input with the selected tokenizer. The default input budget is 7,680 tokens per task. The Qwen preset now has a 2,048-token final output budget; generic custom-model defaults remain 512 unless overridden. Oversized selections are processed in bounded batches rather than silently truncated; details follow below.

Answers stream as text, then render as Markdown when the worker finishes. **Stop** terminates the worker and leaves any partial answer visible. Browsing mail or editing the next question/settings/language preserves the current answer and does not alter the running request. Switching models cancels active generation and unloads the old model, preserving any partial output. The answer header records its original email snapshot and LLM-call count; changed selection is indicated for the next request. Starting a new answer, fetching, disconnecting, or closing the app clears the old answer. One model process stays warm between requests. Explicit Unload, Stop, model switching, application exit, or five idle minutes release it. The idle timer pauses during generation. Request data and caches are cleared after each workflow; warm model weights do not provide implicit conversation history. Worker inputs travel through stdin, outputs through stdout, never command-line arguments or temporary files. Offline mode and local-only tokenization are enforced, remote model code is disabled, and raw runtime diagnostics are neither shown nor logged. Source-reference quality and resistance to instructions in mail still need the planned evaluation set.


### Summaries and large selections

**Summarize** works with one or multiple selected emails, even when the question field is empty. Text entered above the buttons becomes additional summary instructions (for example, “Use Turkish; focus on deadlines”). Those instructions remain in RAM. **Ask emails** continues to use that field as a question.

If the request fits its input budget, it uses one model call. Otherwise, the worker groups emails, splits oversized bodies into numbered excerpts with their original email IDs, extracts relevant evidence, and synthesizes a final answer. No source text is silently cut off. Intermediate notes are compressed and can omit detail; this does not guarantee the fidelity of reading the entire selection in one context. Source-reference and summary-quality evaluations remain necessary.

While running, the progress bar shows completed/created tasks, including a reserved final synthesis task. On success the compact completion message retains those counts and the answer header shows actual LLM calls; the bar is hidden to give output more space. Additional synthesis tasks may be created if the notes themselves need batching; the total increases visibly. Calls run sequentially with one loaded model. The default limit is 64 calls, after which the workflow reports a clear error rather than running indefinitely. Notes use up to 384 output tokens, bounded further by the input budget and configured output limit. Questions or metadata that cannot fit even a single task produce an explicit error. Stop terminates the whole workflow and discards in-flight notes. Browsing or changing next-request options does not change the running workflow's snapshot.

### Inference parameters and local JSON

Expand **Inference parameters** in Caspy to edit sampling, output-token limit, input budget per task, and maximum task count. Edits apply to the next request; **Save model profile** persists them. **Reload JSON** reads manual edits. Profiles are keyed by the preset repository ID or the exact local model path.

The local file is `~/Library/Application Support/Ghost-box/inference-settings.json` on macOS (Qt's application-data directory on Windows). Hover over the profile message to see its path. It is initialized from the small reviewed [inference_defaults.json](ghost_box/models/data/inference_defaults.json); only numeric parameters and profile/source identifiers belong there. Do not put private instructions or email content in this file. Invalid JSON, unknown parameters, and out-of-range values are rejected rather than silently accepted or overwritten.

For the Qwen preset, the [base model card's non-thinking general-task recommendations](https://huggingface.co/Qwen/Qwen3.5-4B#best-practices) supply temperature 0.7, top-p 0.8, top-k 20, min-p 0, presence penalty 1.5, and repetition penalty 1.0. Input/output budgets and task caps are Ghost-box defaults, not Hugging Face recommendations. Other models start with the generic `default` profile; add a `profiles` entry or save one through the UI. MLX penalties use the runtime's full token-history window; numerical settings do not imply identical behavior across runtimes. Non-thinking mode is requested; custom chat templates must support it.

### Memory and GGUF

Caspy shows the actually loaded model and **loading / idle / generating / unloading / unloaded** states and reports **worker peak RAM** while the model is loaded. This includes the model, runtime, tokenizer, and caches; it is not an exact measurement of weights alone. MLX additionally reports active and peak allocator memory. These measurements overlap and must not be summed. Dedicated GPU VRAM is not measured. Peak measurements cover the worker's loaded session, potentially across several questions. After Unload, Stop, idle timeout, or exit, the model is released; historical measurements remain only in RAM while the application stays open.

Choose **Choose GGUF file…** for a local instruction/chat model with an embedded chat template. The optional `llama-cpp-python==0.3.36` backend uses llama.cpp in the same worker, with local tokenization, RAM-only task state, and streamed output. It never downloads a model automatically. GGUF files without a supported embedded chat template fail clearly rather than using a guessed format. Hardware acceleration depends on the installed llama.cpp build; unsupported architectures or templates remain possible.

To enable both runtimes on this Mac:

```sh
uv run --locked --extra inference --extra gguf main.py
```

For GGUF alone (including Windows):

```sh
uv run --locked --extra gguf main.py
```

The optional llama.cpp binding can require a native compiler when no compatible wheel exists; see its [installation documentation](https://github.com/abetlen/llama-cpp-python#installation). Both MLX and a temporary small GGUF model were smoke-tested on Apple Silicon using synthetic messages. Native Windows execution and model-quality evaluations remain pending.


### Readability and response language

The top account toolbar has a **Response language** preference, initially **Türkçe**, with English available. It persists in Qt settings and is applied to both questions and summaries, unless the user explicitly requests another response language. Changing it does not rewrite an existing answer.

The interface uses the OS general UI font, with a 13-point minimum for controls and a 14-point minimum for email, question, and answer text. Larger system font sizes are preserved. The answer receives most of the adjustable vertical space; email preview remains above it. Completed output is rendered by native Qt Markdown support without a browser engine or extra dependency.

### Code layout

```text
main.py                     # launcher
assets/                     # Caspy artwork
ghost_box/                  # application package
  ui/                       # window, model panel, Markdown answer view
  mail/                     # Gmail, RAM store, parsing, context, batch tasks
  models/                   # downloads, settings, backends, worker
    data/                   # pinned manifest and default numeric profiles
tests/                      # synthetic/offline checks
```

The local, ignored `oauth-client.json` stays beside `main.py`. Inference workers launch as `python -m ghost_box.models.worker` from the application root, preserving imports even when the launcher is invoked from another working directory. No mail content is saved by this organization change.


### Load, unload, and output limits

**Load** prepares the selected local model without requiring Gmail or selected emails. Ask, Summarize, and Follow up also load it on demand. **Unload** releases an idle/loading worker; during generation use **Stop**, which cancels and unloads it. Model switching unloads the previous worker. Profile changes take effect through Reload or the next request, which restarts the worker when needed. Only one worker/model is retained. It reads commands from stdin while idle, with no background inference or network polling.

Five idle minutes after loading or finishing a request, the UI terminates the worker. The timer is stopped while generating and restarted after completion. Worker protocol commands are only `load` and `run`; email-bearing request dictionaries and generation caches are cleared before waiting for another command. The UI keeps the displayed answer and its source snapshot in RAM, so unloading does not erase useful output.

The earlier 512-token Qwen limit was a Ghost-box setting, not the model's maximum. The [Qwen non-thinking example](https://huggingface.co/Qwen/Qwen3.5-4B#instruct-or-non-thinking-mode) uses 32,768 tokens. Ghost-box chooses **2,048** as a practical initial preset budget and allows up to **32,768** in Advanced settings, subject to the loaded model's combined context limit. When a final generation reaches its limit, the UI labels it **partial** rather than reporting normal completion. Increase Output tokens and retry; no automatic continuation hides additional calls. Versioned JSON migration raises legacy Qwen settings still at 512 to 2,048 and preserves other customized limits.

The inference panel includes an illustrative attention-cache projection for supported MLX configs. For this Qwen preset, the assumed FP16/BF16 full-attention cache grows by about **32 MiB per 1,024 additional tokens**. This is derived from its full-attention layer count, KV heads, and head dimension. It excludes model weights, recurrent-state caches, padding, activation/workspace allocations, and runtime overhead. A higher output ceiling can permit more generation time and cache growth; actual usage depends on how much is generated. Unknown/GGUF projections are explicitly unavailable rather than guessed. Measured process peak RAM and MLX active/peak allocations remain separate from this illustration.

### Follow-ups, BM25, and elapsed time

**Follow up** becomes active once an answer exists, including when the input is empty. Clicking it with an empty input focuses the question field and shows a prompt without clearing the answer or starting inference. Type a question and press **Follow up** to ask about the last answer or summary using its original source emails, even if you have selected other emails for preview. The explicit context contains only the previous request and answer, plus that source snapshot; it is a bounded conversation, not an unlimited chat transcript. A follow-up replaces the displayed answer but continues using those original emails. Ask emails starts from the current selection instead. All context remains in RAM. Very long previous answers can require a higher input budget.

Enable **Use BM25 search for questions** to let the model formulate a keyword query for a small read-only local search tool. One additional, counted model call returns a strictly validated JSON query; application code runs standard-library BM25 within the question's scoped emails and displays the query and match count. Search results provide compact relevance hints; all scoped emails still accompany the answer workflow. Follow-up search uses its original source snapshot. Summarize always covers selected mail directly. Tool calls share the overall task cap, and no other tool names/actions are accepted.

Completion notifications and answer headers show elapsed seconds. This is wall-clock time from request submission through completion, including model loading/reloading when required, search planning, all batch calls, and cleanup. It excludes earlier mail fetching and manual loading. A manually preloaded model therefore gives a warm-request timing. No private prompts, answers, or timing logs are persisted.


### Summary source attribution

Summarize now processes each selected email independently. Each section's source link, subject, and sender are attached by application code; generated citation labels are removed from the summary body. A summary call receives only that email, and an oversized email is split/combined only with excerpts of itself. There is no final model-written synthesis across different emails in this mode. This prevents the model from assigning multiple unrelated emails to one summary source number.

This costs at least one model call per email; the same warm model is reused. Task limits and progress account for additional calls needed by oversized emails. Summaries appear one completed email at a time. Ask emails and Follow up still support cross-email questions with model-generated citations, which require quality evaluation. Correct application-owned source identity does not itself prove every generated statement is factually accurate.
