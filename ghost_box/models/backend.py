"""Two explicit local runtimes. Imported only by the inference worker."""

from pathlib import Path

from ..mail.tasks import TaskError


def load_backend(path, params):
    if path.suffix.lower() == '.gguf':
        return GGUFBackend(path, params)
    return MLXBackend(path, params)


class MLXBackend:
    def __init__(self, path, params):
        import mlx.core as mx
        from mlx_lm import load
        from mlx_lm.sample_utils import make_sampler, make_logits_processors

        self.mx, self.params = mx, params
        self.model, self.tokenizer = load(path, tokenizer_config={
            'local_files_only': True, 'trust_remote_code': False,
        })
        self.sampler = make_sampler(temp=params['temperature'], top_p=params['top_p'],
                                    top_k=params['top_k'], min_p=params['min_p'])
        self.processors = make_logits_processors(
            presence_penalty=params['presence_penalty'], presence_context_size=0,
            repetition_penalty=params['repetition_penalty'] if params['repetition_penalty'] != 1 else None,
            repetition_context_size=0,
        )
        import json
        config = json.loads((path / 'config.json').read_text())
        self.context_length = config.get('text_config', config).get('max_position_embeddings', 8192)

    def render(self, system, user):
        prompt = self.tokenizer.apply_chat_template([
            {'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            tokenize=False, add_generation_prompt=True, enable_thinking=False)
        return prompt, len(self.tokenizer.encode(prompt))

    def generate(self, prompt, maximum):
        from mlx_lm import stream_generate
        self.finish_reason = None
        # A fresh KV cache for each task; no prompt cache files or conversation history.
        for response in stream_generate(self.model, self.tokenizer, prompt=prompt,
                                        max_tokens=maximum, sampler=self.sampler,
                                        logits_processors=self.processors):
            if response.finish_reason:
                self.finish_reason = response.finish_reason
            yield response.text

    def clear_request(self):
        import gc
        gc.collect()
        self.mx.clear_cache()

    def memory(self):
        return f'MLX active: {self.mx.get_active_memory() / 2**30:.2f} GiB · peak: {self.mx.get_peak_memory() / 2**30:.2f} GiB'


class GGUFBackend:
    def __init__(self, path, params):
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Jinja2ChatFormatter

        # Only local files; no server, model downloader, or disk prompt cache.
        with path.open('rb') as file:
            if file.read(4) != b'GGUF':
                raise TaskError('The selected file is not a GGUF model.')
        self.params = params
        self.model = Llama(model_path=str(path), n_gpu_layers=-1, verbose=False,
                           n_ctx=params['max_input_tokens'] + params['max_output_tokens'] + 1,
                           last_n_tokens_size=params['max_input_tokens'] + params['max_output_tokens'])
        template = self.model.metadata.get('tokenizer.chat_template')
        if not isinstance(template, str):
            raise TaskError('This GGUF needs an embedded chat template. Choose an instruction/chat model with one.')
        def token_text(identifier):
            return self.model.detokenize([identifier], special=True).decode('utf-8', errors='replace') if identifier >= 0 else ''
        self.formatter = Jinja2ChatFormatter(template=template,
                                            eos_token=token_text(self.model.token_eos()),
                                            bos_token=token_text(self.model.token_bos()))
        lengths = [value for key, value in self.model.metadata.items() if key.endswith('.context_length')]
        self.context_length = min(int(value) for value in lengths) if lengths else self.model.n_ctx()

    def render(self, system, user):
        formatted = self.formatter(messages=[{'role': 'system', 'content': system},
                                            {'role': 'user', 'content': user}], enable_thinking=False)
        tokens = self.model.tokenize(formatted.prompt.encode(), add_bos=False, special=True)
        return (tokens, formatted.stop, formatted.stopping_criteria), len(tokens)

    def generate(self, prompt, maximum):
        self.finish_reason = None
        tokens, stop, stopping = prompt
        for response in self.model.create_completion(
            prompt=tokens, stop=stop or [], stopping_criteria=stopping,
            stream=True, max_tokens=maximum, temperature=self.params['temperature'],
            top_p=self.params['top_p'], top_k=self.params['top_k'], min_p=self.params['min_p'],
            presence_penalty=self.params['presence_penalty'], repeat_penalty=self.params['repetition_penalty'],
        ):
            choice = response['choices'][0]
            if choice.get('finish_reason'):
                self.finish_reason = choice['finish_reason']
            yield choice['text']

    def clear_request(self):
        import llama_cpp
        self.model.reset()
        memory = llama_cpp.llama_get_memory(self.model.ctx)
        if memory is not None:
            llama_cpp.llama_memory_clear(memory, True)
        self.model._input_ids.fill(0)
        self.model._scores.fill(0)

    def memory(self):
        return ''  # Process peak RAM is reported separately for both backends.
