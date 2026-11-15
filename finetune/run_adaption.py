"""Upload the extractor dataset to Adaption and run AutoScientist (SFT fine-tune).

Setup:  pip install "adaption>=0.7.0"   and put ADAPTION_API_KEY in your local .env (never commit it).
Steps:  python finetune/run_adaption.py check      # offline: row count, columns, no key needed
        python finetune/run_adaption.py upload     # upload adaption_train.jsonl, wait for ingestion
        python finetune/run_adaption.py train      # start the run (add --model, --target-win-rate)
        python finetune/run_adaption.py status     # poll once; `wait` blocks until it finishes
        python finetune/run_adaption.py download   # best checkpoint -> finetune/checkpoints/best-checkpoint.tgz
        python finetune/run_adaption.py models     # list supported base models
Ids are kept in finetune/.adaption_state.json (gitignored), so each step resumes where the last stopped.

Written from Adaption's public docs (docs.adaptionlabs.ai) and not yet run against the live API:
the SDK names below (upload_file, wait_for_completion, autoscientist.create/get/download) follow the docs;
if a call fails, check the reference page for that method first.
"""
import argparse, json, os, sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "adaption_train.jsonl"
STATE = HERE / ".adaption_state.json"
MIN_ROWS = 1000  # SFT minimum per the docs
COLUMN_MAPPING = {"prompt": "prompt", "completion": "completion"}


def load_env():
    """Read ADAPTION_API_KEY from the repo's local .env if it is not already exported."""
    env = HERE.parent / ".env"
    if "ADAPTION_API_KEY" not in os.environ and env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ADAPTION_API_KEY":
                os.environ[k.strip()] = v.strip().strip("'\"")


def client():
    load_env()
    if not os.environ.get("ADAPTION_API_KEY"):
        sys.exit("ADAPTION_API_KEY is not set. Put it in your local .env (claim credit under My Pass).")
    try:
        from adaption import Adaption
    except ImportError:
        sys.exit('Install the SDK first: pip install "adaption>=0.7.0"')
    return Adaption()


def state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save(**kw):
    s = state(); s.update(kw); STATE.write_text(json.dumps(s, indent=2))


def need(key, step):
    v = state().get(key)
    if not v:
        sys.exit(f"No {key} saved. Run `{step}` first.")
    return v


def cmd_check(_):
    rows = [json.loads(l) for l in DATA.read_text().splitlines() if l.strip()]
    bad = [i for i, r in enumerate(rows, 1) if not (isinstance(r.get("prompt"), str) and isinstance(r.get("completion"), str))]
    print(f"{DATA.name}: {len(rows)} rows, columns {sorted(rows[0])}")
    if bad:
        sys.exit(f"rows with non-string prompt/completion: {bad[:5]}")
    if len(rows) < MIN_ROWS:
        sys.exit(f"{len(rows)} rows is below Adaption's SFT minimum of {MIN_ROWS}. Re-run make_dataset.py with more rows.")
    print("ok: meets the 1000-row SFT minimum")


def cmd_upload(_):
    cmd_check(_)
    c = client()
    ds = c.datasets.upload_file(str(DATA), processing_mode="raw", column_mapping=COLUMN_MAPPING)
    dataset_id = ds.dataset_id
    save(dataset_id=dataset_id)
    print("dataset_id", dataset_id, "- waiting for ingestion")
    done = c.datasets.wait_for_completion(dataset_id)
    print("status", done.status, "rows", getattr(done, "row_count", None))
    if done.status != "succeeded":
        sys.exit(f"ingestion ended with status {done.status}")


def cmd_train(a):
    c = client()
    kw = dict(dataset_id=need("dataset_id", "upload"), model=a.model, training_method="instruction",
              data_format="instruction",  # columns inferred by the server (an explicit mapping is rejected for uploaded raw data)
              max_iterations=a.max_iterations, target_win_rate=a.target_win_rate,
              idempotency_key=a.idempotency_key or f"portshift-extractor-{state()['dataset_id'][:8]}")
    run = c.autoscientist.create(**kw)
    save(run_id=run.id)
    print("run_id", run.id, "status", run.status)


def show(run):
    print(f"status={run.status} iterations={run.iterations_completed}/{run.max_iterations} "
          f"best_win_rate={run.best_win_rate} target={run.target_win_rate} download={run.download_available}")
    if run.status == "failed":
        print("error:", run.error)


def cmd_status(_):
    show(client().autoscientist.get(need("run_id", "train")))


def cmd_wait(_):
    from adaption import TrainingTimeout
    c = client()
    try:
        run = c.autoscientist.wait_for_completion(need("run_id", "train"))
    except TrainingTimeout as exc:  # stops waiting, not training; just call wait again
        sys.exit(f"still running (last status {exc.last_status}); run `wait` again")
    show(run)
    if run.best_win_rate is not None and run.target_win_rate is not None and run.best_win_rate < run.target_win_rate:
        print("note: succeeded but best_win_rate is below the target")


def cmd_download(_):
    c = client(); run_id = need("run_id", "train")
    run = c.autoscientist.get(run_id)
    if run.status != "succeeded" or not run.download_available:
        sys.exit(f"checkpoint not available (status={run.status})")
    out = HERE / "checkpoints"; out.mkdir(exist_ok=True)
    with c.autoscientist.with_streaming_response.download(run_id) as resp:
        resp.stream_to_file(str(out / "best-checkpoint.tgz"))
    print("saved", out / "best-checkpoint.tgz", "(extract with: tar xf best-checkpoint.tgz)")


def cmd_models(_):
    for m in client().autoscientist.list_models().models:
        print(m.id)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "upload", "status", "wait", "download", "models"):
        sub.add_parser(name)
    t = sub.add_parser("train")
    t.add_argument("--model", default="Qwen/Qwen3.5-2B", help="exact id from `models` (default: smallest available)")
    t.add_argument("--max-iterations", type=int, default=3)
    t.add_argument("--target-win-rate", type=float, default=0.7)
    t.add_argument("--idempotency-key")
    a = p.parse_args()
    {"check": cmd_check, "upload": cmd_upload, "train": cmd_train, "status": cmd_status,
     "wait": cmd_wait, "download": cmd_download, "models": cmd_models}[a.cmd](a)
