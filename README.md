# ghost-box

A lightweight desktop email assistant powered by **Caspy**, your local small language model companion, with on-device inference via MLX and llama.cpp.

Ghost-box helps you summarize email conversations, search downloaded messages, and ask questions with references to the original mail. It is designed for macOS and Windows, with a small Python codebase that is straightforward to read, review, and maintain.

> **Status: Gmail fetch increment.** Read-only Google sign-in works. Manual date/time-range fetching, local SQLite replacement, and a plain-text mail reader are implemented and checked with synthetic data. Live mailbox fetching still needs user verification. Models, search, cleanup controls, and packaging remain planned.

## Purpose

Reduce the time spent reading and finding email while keeping AI processing on the user's device. The first release should complete one useful workflow:

1. Connect a mail account.
2. Click **Fetch** to download messages within a selected date range.
3. Open a message or conversation and request a summary.
4. Search downloaded mail or ask a question.
5. Follow the answer's references back to the supporting messages.
6. Let the model unload when idle to release memory.

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
| Storage | Local SQLite database for messages, search, and application state |
| Cleanup | Remove downloaded mail and derived local data through an explicit user action |

The application must distinguish **no supporting message found** from **no such message exists**. Answers should state the relevant local search coverage, including the downloaded date range and the last successful fetch.

## Proposed implementation

The starting stack is **Python, PySide6 (Qt Widgets), and SQLite**. A simple desktop interface avoids the need for a browser engine, JavaScript frontend, or local web server.

| Component | Responsibility |
| --- | --- |
| PySide6 interface | Display messages, accept questions, and show operation and model status |
| Python application core | Coordinate fetching, storage, retrieval, and inference |
| SQLite with FTS5 | Store downloaded mail and provide local full-text search |
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

The initial model preset is [mlx-community/Qwen3.5-4B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-4B-MLX-4bit). Confirm text-only runtime compatibility before integrating it. [Occam](https://huggingface.co/cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora), a Turkish concise-response LoRA, is an additional candidate after conversion and task-specific evaluation. Caspy is the companion's name; the underlying model can change.

Choose the default using email summarization and question-answering results, including factual faithfulness, retrieval quality, latency, and memory usage. Concise output alone is insufficient.

### Model lifecycle

Expose a small set of understandable states: **not configured**, **downloading**, **unloaded**, **loading**, **ready**, **generating**, and **error**.

- Show download progress and support cancellation and retry.
- Validate the configured model before starting inference.
- Load on the first inference request, independently of mail fetching.
- Keep the worker alive briefly for follow-up requests.
- Stop it after a configurable idle timeout or an explicit unload action.
- Never unload during an active generation; let the user cancel it first.
- Surface failures without freezing the interface or repeatedly restarting the worker.

## Retrieval and answers

Use a bounded, predictable workflow:

```text
Question → validated filters → local search → selected source messages → answer with references
```

Begin with SQLite FTS5 and metadata filters. Do not introduce an embedding model or vector service until actual retrieval failures justify the additional complexity. The model must not execute SQL, shell commands, or arbitrary tools.

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

The desktop interface is in [main.py](main.py). The UI dependency in [pyproject.toml](pyproject.toml) is **PySide6-Essentials**, which provides Qt Widgets without the additional PySide6 Addons package. Its required binding library, shiboken6, is installed transitively. [uv.lock](uv.lock) records exact dependency versions.

PySide6-Essentials remains pinned to the checked version, 6.10.2. A recurring Cocoa discovery error on the development Mac was traced to macOS hidden flags on installed plugin files; changing Qt versions alone did not fix that underlying cause. Before creating the application, `prepare_qt_plugins()` clears only the hidden flag within the installed Qt plugin directory on macOS, preserving other file flags. This handles the condition on each launch without a manual repair command or additional dependency. The source of the recurring hidden flags has not been identified.

The account toolbar is implemented in [main.py](main.py); [gmail.py](gmail.py) handles OAuth and native credential storage. Two additional direct dependencies are `google-auth-oauthlib` for Google's browser-based OAuth with PKCE, and `keyring` for macOS Keychain / Windows Credential Manager. Their transitive dependencies are recorded in the lockfile. The full Gmail API SDK is not installed.

### Connect Gmail

For users, the flow is **Connect Gmail → Google sign-in → consent → connected**. There is no file picker or Google Cloud setup for end users.

The following setup is performed once by the application maintainer:

1. Create or select a project in [Google Cloud Console](https://console.cloud.google.com/) and enable **Gmail API**.
2. Configure the Google Auth Platform consent screen. Choose Internal only if the project and users belong to the appropriate Workspace organization; otherwise use External and add your account as a test user while testing.
3. Add the read-only scope `https://www.googleapis.com/auth/gmail.readonly` to the application's data access configuration.
4. Create an OAuth client with application type **Desktop app**, then download its JSON file. A Web application client is not interchangeable.
5. Save the downloaded configuration as `oauth-client.json` beside `gmail.py`. This filename is ignored by Git. Include the configuration in distributed builds; do not include user tokens. The configuration remains local and untracked.
6. Launch Ghost-box, click **Connect Gmail**, and finish sign-in and consent in the system browser. The application checks the Gmail profile and saves credentials in the OS credential store. No email messages are downloaded.

The official flow uses a temporary loopback callback listener on `127.0.0.1`, not an application web server. Browser authorization waits up to 60 seconds; network requests have 20-second timeouts. If you abandon sign-in, wait for it to time out before retrying. Closing the application is deferred while an account operation is running.

On startup, the application reads only the locally saved account identity; it does not contact Google or assert that saved credentials remain valid. **Disconnect** removes the local credential entry, without changing mail or revoking Google's server-side grant. To revoke that grant as well, remove Ghost-box from your Google Account's connected applications.

Google testing restrictions, restricted-scope verification, and Workspace administrator policies can affect sign-in. See [Google's desktop OAuth documentation](https://developers.google.com/identity/protocols/oauth2/native-app). There is no plaintext-token fallback if the native credential store is unavailable.

### Fetch and read mail

**From** defaults to today at **00:00** and **To** to today at **23:59**. Both include editable hours and minutes. Times follow this computer's local timezone, and the entire displayed To minute is included (for example, 10:45 includes messages through 10:45:59.999). Filtering uses Gmail's `internalDate`, with epoch-second queries and an exact millisecond boundary check; it does not rely on the email's Date header. See [Google's timezone guidance](https://developers.google.com/workspace/gmail/api/guides/filtering).

Sent mail is included; Spam, Trash, and Drafts are excluded. **Cancel** stops between network requests and discards the incomplete replacement. Each successful Fetch replaces the connected account's previous local messages with the new results, including clearing them when the result is empty. Replacement uses one SQLite transaction: failure or cancellation preserves the previous local emails, while a successful fetch commits the new set. Other accounts' local data is unaffected. No requests are made to mark mail as read or modify Gmail.

Select a row to read the message as plain text. HTML-only mail is converted to text without rendering HTML, loading images, or following links. This initial implementation downloads raw MIME, so attachment bytes may be transferred as part of a message, but attachments are not separately extracted, stored, or displayed.

Messages are saved in `mail.sqlite3` under Qt's local application-data directory (`~/Library/Application Support/Ghost-box/` on macOS). The list shows the connected account's most recent successfully fetched set, newest first. Existing data from older versions is replaced on the next successful fetch. Disconnect hides that account's messages without deleting the database. Local data is not application-encrypted yet. Delete/clear controls and persistent fetch-coverage tracking remain the next increments.

New files for this step are [mail_store.py](mail_store.py) (SQLite operations) and [mail_text.py](mail_text.py) (MIME-to-text conversion); fetching is in [gmail.py](gmail.py), and the UI remains in [main.py](main.py). No new dependencies were added.

Run the checks without Google access or real credentials:

```sh
uv run --locked python -m unittest discover -s tests -v
```

Model downloads and inference are not implemented yet.
