"""finetune/run_adaption.py for v2 datasets, with its own data file, state file and checkpoint folder per tag,
so the v1 run's ids (finetune/.adaption_state.json) and checkpoint are never overwritten.

    python finetune/v2/run_adaption_v2.py --tag a --data finetune/v2/adaption_train_v2.jsonl upload
    python finetune/v2/run_adaption_v2.py --tag a train --max-iterations 3 --target-win-rate 0.8
    python finetune/v2/run_adaption_v2.py --tag a status | wait | download
State: finetune/v2/runs/<tag>/state.json; checkpoint: finetune/v2/runs/<tag>/checkpoints/best-checkpoint.tgz.
"""
import pathlib, sys

V2 = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(V2.parent))
import run_adaption as ra  # noqa: E402

args = sys.argv[1:]
tag = args[args.index("--tag") + 1]; del args[args.index("--tag"):args.index("--tag") + 2]
run_dir = V2 / "runs" / tag; run_dir.mkdir(parents=True, exist_ok=True)
if "--data" in args:
    i = args.index("--data"); (run_dir / "data_path.txt").write_text(args[i + 1]); del args[i:i + 2]
data = (run_dir / "data_path.txt").read_text().strip() if (run_dir / "data_path.txt").exists() else None
ra.load_env()  # reads ADAPTION_API_KEY from the repo .env before HERE is moved
ra.HERE = run_dir                     # checkpoints go to runs/<tag>/checkpoints
ra.STATE = run_dir / "state.json"
if data:
    ra.DATA = pathlib.Path(data).resolve()
sys.argv = [sys.argv[0]] + args
exec(compile(pathlib.Path(ra.__file__).read_text().split('if __name__ == "__main__":', 1)[1].replace("\n    ", "\n"),
             ra.__file__, "exec"), ra.__dict__)
