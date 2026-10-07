# SWE-bench Verified experiment

This directory defines the reproducible external benchmark entry point for
Stewart-SWE-AF.

## Dataset

Use the official `princeton-nlp/SWE-bench_Verified` test split. It contains
500 human-validated instances. The official evaluator applies generated patches
inside Docker and runs the benchmark tests.

## Subset protocol

Do not hand-pick tasks.

Generate the initial controlled subset with:

```bash
python benchmarks/swebench/select_verified_subset.py \
  --size 10 \
  --seed stewart-verified-v1 \
  --output benchmarks/swebench/verified-subset-v1.json
```

The selector hashes the public `instance_id` together with a fixed seed.
The resulting IDs are the experimental sample and must be committed before
agent execution.

The selector does not inspect gold patches, test patches, difficulty, or model
results.

## Gold integrity check

Before any agent run:

```bash
swebench eval verified --gold \
  -i sympy__sympy-20590 \
  --run-id stewart-gold-validation
```

The gold run is only an environment/evaluator integrity check. It is not a
Stewart result.

## Agent evaluation

The agent must produce one prediction per evaluated instance in the official
JSONL format:

```json
{"instance_id":"...","model_name_or_path":"...","model_patch":"..."}
```

Then evaluate with the official harness:

```bash
swebench eval verified \
  -p predictions.jsonl \
  --run-id <unique-run-id> \
  -j <workers>
```

The official evaluator stores run metadata and reports under
`logs/evaluation/<run-id>/`.

## Accounting

Each experiment must additionally persist:

- provider/model
- runtime/entrypoint
- input/output tokens
- LLM call count
- retries and causes
- wall-clock duration
- API cost
- infrastructure cost
- solved/failed/timeout/infrastructure-error
- evaluator run ID

The primary economic metric is:

```text
total model + infrastructure cost / solved tasks
```

Undefined when zero tasks are solved.

## Experimental comparison

For the first controlled comparison, freeze the subset and model:

A. full SWE-AF
B. `implement_issue`

Then introduce the low-cost model candidate as a separate factor.

Do not mix model changes and harness changes in the same causal comparison.
