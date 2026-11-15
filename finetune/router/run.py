"""Run the request-reader fine-tune on Adaption with its own data file and its own saved ids.

  python finetune/router/run.py check | upload | train | status | wait | download

Same steps as finetune/run_adaption.py (it is that script, pointed at finetune/router/train.jsonl), with the
dataset and run ids kept in finetune/router/.adaption_state.json so the extractor's ids are not overwritten.
The checkpoint is saved to finetune/router/checkpoints/.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import run_adaption as base  # noqa: E402

import os  # noqa: E402

# ROUTER_RUN names the run whose ids are kept: "v1" (the first request format) or "v2" (with timing and details).
TAG = os.environ.get("ROUTER_RUN", "v2")
base.DATA = HERE / "train.jsonl"
base.STATE = HERE / (".adaption_state.json" if TAG == "v1" else f".adaption_state_{TAG}.json")


def download(_):
    client, run_id = base.client(), base.need("run_id", "train")
    run = client.autoscientist.get(run_id)
    if run.status != "succeeded" or not run.download_available:
        sys.exit(f"checkpoint not available (status={run.status})")
    out = HERE / "checkpoints" / TAG
    out.mkdir(parents=True, exist_ok=True)
    with client.autoscientist.with_streaming_response.download(run_id) as resp:
        resp.stream_to_file(str(out / "best-checkpoint.tgz"))
    print("saved", out / "best-checkpoint.tgz")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["check", "upload", "train", "status", "wait", "download"])
    ap.add_argument("--model", default="Qwen/Qwen3.5-2B")
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--target-win-rate", type=float, default=0.7)
    a = ap.parse_args()
    a.idempotency_key = f"portshift-request-reader-{base.state().get('dataset_id', 'new')[:8]}"
    {"check": base.cmd_check, "upload": base.cmd_upload, "train": base.cmd_train, "status": base.cmd_status,
     "wait": base.cmd_wait, "download": download}[a.cmd](a)
