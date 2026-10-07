"""Select a deterministic, auditable subset from SWE-bench Verified.

The selector operates on the official 500-row test split and records the exact
instance IDs used by an experiment. It does not inspect gold patches or tests
when selecting tasks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from datasets import load_dataset


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--seed", default="stewart-verified-v1")
    p.add_argument("--output", type=Path, default=Path("verified-subset.json"))
    args = p.parse_args()

    ds = load_dataset("princeton-nlp/SWE-bench_Verified", split="test")
    if args.size < 1 or args.size > len(ds):
        raise SystemExit(f"size must be between 1 and {len(ds)}")

    ranked = sorted(
        ds,
        key=lambda row: hashlib.sha256(
            f"{args.seed}\0{row['instance_id']}".encode()
        ).hexdigest(),
    )
    ids = [row["instance_id"] for row in ranked[: args.size]]

    payload = {
        "dataset": "princeton-nlp/SWE-bench_Verified",
        "split": "test",
        "dataset_rows": len(ds),
        "selection": "sha256(seed + NUL + instance_id), ascending",
        "seed": args.seed,
        "size": args.size,
        "instance_ids": ids,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
