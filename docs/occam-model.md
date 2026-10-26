# Trying Occam in Ghost-box

The [published repository](https://huggingface.co/cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora)
now includes the original PEFT adapter and a complete, merged **Q4_K_M GGUF**.
Download [Qwen3.5-4B-Turkish-Concise-Q4_K_M.gguf](https://huggingface.co/cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora/resolve/52d34aa4b74ed0241e67a103be3413c0a34373f5/Qwen3.5-4B-Turkish-Concise-Q4_K_M.gguf)
(2,708,804,224 bytes), then select **Choose GGUF file…** in Caspy.
Ghost-box does not load the PEFT adapter directly.

The GGUF loaded and generated through Ghost-box on Apple Silicon; Windows remains
untested. This is an experimental model, not a replacement preset: synthetic tests
exposed factual errors and incorrect draft addressees. See the repository's
[GGUF deployment report](https://huggingface.co/cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora/blob/main/GGUF.md)
for provenance, benchmark outputs and limitations. MLX conversion remains unverified.
The following recipe documents preparation rather than a required app setup step.

The deployment path is **original BF16 base + LoRA → merged Hugging Face checkpoint →
MLX 4-bit or GGUF Q4_K_M**. Merge before quantizing. Do not treat the PEFT adapter as
an MLX adapter or merge it directly into the existing quantized preset.

## 1. Merge outside the application environment

This preparation requires large base weights, temporary disk space and considerably
more RAM than running a 4-bit model. It can be done on a separate machine. No changes
to Ghost-box dependencies are required.

Save this as `merge_occam.py` in a separate model-preparation directory:

```python
from pathlib import Path
import torch
from transformers import Qwen3_5ForConditionalGeneration, AutoProcessor
from peft import PeftModel

base_id = 'unsloth/Qwen3.5-4B'
base_revision = '3764fa359b9082ea5a1e4a5e3ac3aaf6e9671636'
adapter_id = 'cbarkinozer/Qwen3.5-4B-Turkish-Concise-Lora'
adapter_revision = '1a8a07ff2a29f51a2b6a635a8c219191a7377996'
output = Path('occam-merged')
if output.exists():
    raise SystemExit('Choose a new output directory; existing files are not overwritten.')

base = Qwen3_5ForConditionalGeneration.from_pretrained(
    base_id, revision=base_revision, dtype=torch.bfloat16,
    device_map='cpu', trust_remote_code=False,
)
model = PeftModel.from_pretrained(base, adapter_id, revision=adapter_revision)
model.merge_and_unload(safe_merge=True).save_pretrained(output, safe_serialization=True)
AutoProcessor.from_pretrained(
    base_id, revision=base_revision, trust_remote_code=False,
).save_pretrained(output)
print(output.resolve())
```

Run in an isolated preparation environment, not `uv add` in Ghost-box:

```sh
uv run --python 3.11 --with torch --with 'transformers>=5' \
  --with 'peft>=0.21' --with accelerate python merge_occam.py
```

The published GGUF was prepared in an isolated export environment; consult its export
manifest for exact resolved versions. The abbreviated recipe below is illustrative.
The architecture and adapter must be supported by the installed Transformers/PEFT
versions. Record the resolved versions and validate the merged checkpoint before
publishing it. The base and adapter revisions above come from the model card's
recorded training/evaluation artifacts. The card explicitly says the official Qwen
and Unsloth tokenizer/config/template files differed; preserve the pinned Unsloth
processor rather than substituting the current official tokenizer.

## 2a. Apple Silicon: convert the merged checkpoint to MLX

From the Ghost-box directory, using its pinned MLX runtime:

```sh
uv run --locked --extra inference python -m mlx_lm convert \
  --hf-path /absolute/path/occam-merged \
  --mlx-path /absolute/path/occam-mlx-4bit \
  --quantize --q-bits 4
```

Select **Choose local MLX folder… → occam-mlx-4bit** in Caspy, then use **Try model**.
Conversion of this specific merged multimodal checkpoint through the text-only MLX
converter remains to be validated; do not label it supported until it loads and generates.

## 2b. Windows/macOS: convert to GGUF

With a current, architecture-compatible llama.cpp checkout/build:

```sh
python /path/to/llama.cpp/convert_hf_to_gguf.py \
  /absolute/path/occam-merged --outfile /absolute/path/occam-bf16.gguf --outtype bf16 --no-mtp
/path/to/llama-quantize /absolute/path/occam-bf16.gguf \
  /absolute/path/occam-Q4_K_M.gguf Q4_K_M
```

The converter has its own requirements; use its documented conversion environment.
On Windows use the corresponding `.exe` binary. Select **Choose GGUF file… →
occam-Q4_K_M.gguf** in Caspy. A text-only email assistant does not need a vision projector.

## 3. Verify before comparing or replacing a preset

Start with Turkish **Try model**, then run the synthetic email benchmark. The model
card reports a style/directness improvement but a summarization-faithfulness regression
in its small human-reviewed sample; do not infer better email accuracy from concise output.
The recorded evaluation used thinking disabled, greedy decoding and repetition penalty
1.05; the card also calls out native EOS 248044 versus tokenizer EOS 248046. Verify
termination after conversion. Ghost-box's system prompts, sampling, context and runtime
constitute a different protocol; its benchmark is a new evaluation, not reproduction
of those published scores. Do not change the app's EOS globally to match one artifact.

The published export used llama.cpp commit `7fe450e19305b828c199d602c23a8337aaa1f03b`.
`--no-mtp` is required for this merged checkpoint: optional MTP tensors are absent
after merging, although its saved config still declares an MTP layer.

GGUF SHA-256: `e640ec52d141138a1ee568421c821a9308eb5cdbb94112f3d3f2f77418069857`.
