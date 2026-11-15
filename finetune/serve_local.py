"""Serve a local model behind an OpenAI-compatible chat-completions endpoint, so evals/run_extractor.py can
score the base model and the fine-tuned checkpoint on the held-out set with the same prompts.

  pip install torch transformers peft accelerate
  python finetune/serve_local.py --model Qwen/Qwen3.5-2B --port 8090                                # base
  python finetune/serve_local.py --model Qwen/Qwen3.5-2B --adapter finetune/checkpoints/best --port 8091   # fine-tune
  python evals/run_extractor.py --backend http --url http://127.0.0.1:8090/v1/chat/completions --out preds_base.jsonl

--adapter is the folder extracted from Adaption's best-checkpoint.tgz: a LoRA adapter (adapter_config.json)
is applied on top of --model; a folder with full weights is loaded as the model itself.
Decoding is greedy (temperature 0), so a run is repeatable. Both models get the same chat template.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


def load(model_id: str, adapter: str | None):
    dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
    full = adapter and not (Path(adapter) / "adapter_config.json").exists()
    source = adapter if full else model_id
    tok = AutoTokenizer.from_pretrained(source)
    model = AutoModelForCausalLM.from_pretrained(source, torch_dtype=dtype, device_map="auto")
    if adapter and not full:
        model = apply_adapter(model, adapter)
    model.eval()
    return tok, model


def apply_adapter(model, adapter: str):
    """Put the LoRA weights on the model and refuse to serve unless every one of them landed.

    Adaption trains on the image-and-text build of the model, where the text layers are named
    model.language_model.layers.N; the text-only build loaded here names them model.layers.N. Loaded as is,
    no adapter weight matches and the "fine-tune" silently answers exactly like the base model. So the names
    are mapped to this build, and the number applied is checked against the number in the file."""
    from peft import LoraConfig, get_peft_model, set_peft_model_state_dict
    from safetensors.torch import load_file
    weights = load_file(str(Path(adapter) / "adapter_model.safetensors"))
    config = LoraConfig.from_pretrained(adapter)
    config.exclude_modules = None  # lists vision modules this build does not have
    model = get_peft_model(model, config)
    wanted = {n for n, _ in model.named_parameters() if "lora_" in n}
    for rename in (lambda k: k, lambda k: k.replace(".model.language_model.", ".model.")):
        mapped = {rename(k): v for k, v in weights.items()}
        landed = {k.replace(".lora_A.weight", ".lora_A.default.weight").replace(".lora_B.weight", ".lora_B.default.weight") for k in mapped} & wanted
        if len(landed) == len(weights):
            result = set_peft_model_state_dict(model, mapped)
            if getattr(result, "unexpected_keys", None):
                raise SystemExit(f"adapter weights not applied: {result.unexpected_keys[:3]}")
            print(f"adapter applied: {len(landed)} LoRA tensors of {len(weights)}", flush=True)
            return model
    raise SystemExit(f"the adapter does not fit this model: {len(weights)} tensors in the file, none of the known layer namings matches all of them")


def reply(tok, model, messages, max_tokens: int) -> str:
    try:  # Qwen's template can open a thinking block; the extractor wants the answer only
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    except TypeError:
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tok(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False)
    return tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="Qwen/Qwen3.5-2B")
    ap.add_argument("--adapter")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args()
    tok, model = load(a.model, a.adapter)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = reply(tok, model, body["messages"], int(body.get("max_tokens", 400)))
            data = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    print(f"serving {a.model}{' + ' + a.adapter if a.adapter else ''} on http://127.0.0.1:{a.port}/v1/chat/completions", flush=True)
    HTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
