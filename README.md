# ghost-box

A lightweight desktop email assistant powered by **Caspy**, your local small language model companion, with on-device inference via MLX and llama.cpp.

Ghost-box helps you summarize email conversations, search downloaded messages, and ask questions with references to the original mail. It is designed for macOS and Windows, with a small Python codebase that is straightforward to read, review, and maintain.

> **Status: initial desktop shell.** The application currently opens a mostly empty window. Email, inference, packaging, and security controls below remain planned.

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

The entire application is currently in [main.py](main.py). [pyproject.toml](pyproject.toml) declares one direct dependency, **PySide6-Essentials**, which provides Qt Widgets without the additional PySide6 Addons package. Its required binding library, shiboken6, is installed transitively. [uv.lock](uv.lock) records exact dependency versions.

PySide6-Essentials is pinned to 6.10.2: the initial 6.12.0 installation failed to discover the installed Cocoa platform plugin on the development Mac. The pinned version was checked with the actual launch command and a native-window startup/shutdown check.

Close the window to exit. This increment does not connect to Gmail, store mail, download models, or start a model worker. Installation requires network access; the window itself does not.
