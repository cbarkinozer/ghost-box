# Synthetic model benchmark

Start with [REVIEW.md](REVIEW.md): **20 questions**, expected answers and source IDs.
[mailbox.json](mailbox.json) contains **24 fictional messages**; [cases.json](cases.json)
defines each question, selection, language and expected facts. All addresses use reserved
`.example` domains. Fixture timestamps use epoch milliseconds, matching the mail adapters. This runner never connects to Gmail/Outlook or reads the app's mailbox/settings.

Review without loading a model:

```sh
uv run --locked -m benchmarks.run --list
```

Test one case first, then omit `--case` for all 20:

```sh
uv run --locked --extra inference -m benchmarks.run \
  --model "/absolute/path/to/local/mlx-model" --case q06 \
  --model-id mlx-community/Qwen3.5-4B-MLX-4bit --revision EXACT_REVISION

uv run --locked --extra gguf -m benchmarks.run \
  --model "/absolute/path/Qwen_Qwen3.5-4B-Q4_K_M.gguf" \
  --profile bartowski/Qwen_Qwen3.5-4B-GGUF \
  --model-id Qwen3.5-4B-Q4_K_M --revision EXACT_REVISION \
  --output benchmarks/results/gguf.json
```

On Windows the pinned GGUF runtime is included in the base environment. Use a local
Windows path and `uv run --locked -m benchmarks.run ...`. Models are never downloaded
by the runner. Do not run the benchmark alongside app inference when comparing memory/speed.

Each case gets a fresh subprocess and model load, followed by two requests by default
(`--repeats 2`): first request and warm reuse. Model load is reported separately from
workflow latency. The first-request label does **not** promise an empty OS file cache.
`--timeout 300` limits the whole case including loading and repeats. Failures/timeouts
remain in the report. Reports are saved after each case, under ignored `results/` by default.
Use different output names for model comparisons. Parameters use shipped profiles;
`--parameters settings.json` accepts a complete numeric parameter object, not the UI's
multi-profile file. No seed is currently exposed by the shared backend.

JSON contains generated answers, expected facts, ordinal-to-message-ID mappings,
steps/diagnostics, model/runtime/workflow identity, load time, end-to-end latency,
first visible output time, actual calls, process peak RAM and per-call runtime metrics.
MLX uses its native token/s counters. GGUF uses llama.cpp evaluation counters;
its evaluated decode token count excludes first-token sampling, and its generated
output token count is unavailable. Missing counters/timings are null, never inferred
from characters. Peak RAM is historical process peak, not incremental model size or GPU VRAM.
First visible summary output means the first published card, not an internal extraction token.

Open the JSON and fill in each run's `human_review` fields. Check factual support,
correct citations, Turkish, omissions, refusal and follow-up tool decisions. Lexical
checks merely flag terms for review; they can pass a factually wrong answer. The
Markdown table is a quick timing overview; cold/warm measurements remain distinct
in JSON and should be compared separately. No aggregate accuracy claim is produced
before human review. Metadata questions currently test answer reasoning, not the
pending structured metadata-filter feature. Thread questions expose current summary
limitations rather than assuming chronological thread synthesis already works.

Only built-in synthetic fixtures are supported. Do not replace them with real emails:
this opt-in runner intentionally writes synthetic answers/reports to disk, while the
application's real email workflows remain RAM-only. Do not commit private reports.
