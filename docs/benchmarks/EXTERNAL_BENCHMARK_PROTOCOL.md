# External Benchmark Protocol

## Purpose

Measure SWE-AF as an engineering agent against independent, externally maintained software-engineering benchmarks.

The primary economic objective is **cost per successfully solved task**. Raw solve rate is necessary but is not sufficient for adoption.

## Benchmark hierarchy

### 1. SWE-bench Verified — primary SWE gate

Use the official `princeton-nlp/SWE-bench_Verified` test split (500 engineer-verified instances).

Evaluation must use the official SWE-bench harness. Predictions are evaluated by applying the generated patch in the benchmark environment and running the benchmark tests.

Reference:
- https://github.com/SWE-bench/SWE-bench
- https://www.swebench.com/

### 2. Terminal-Bench — agent/terminal gate

Use Terminal-Bench as a secondary external measure of end-to-end terminal-agent capability.

Record the benchmark's published resolution rate together with token and cost measurements when available.

Reference:
- https://www.tbench.ai/

### 3. todo-app-benchmark — internal regression only

The repository-local todo benchmark is retained for regression testing and development. It is **not** external evidence and must not be used as the primary claim of general SWE capability.

The restored fixture is a reproducible task baseline, not a byte-for-byte recovery of the unavailable historical gitlink target.

## Controlled variables

For every Stewart run record:

- benchmark and exact split/version
- instance IDs
- executor/runtime
- model and provider
- model configuration
- temperature and other relevant generation parameters
- token input/output counts when available
- total LLM calls
- retries and retry causes
- wall-clock latency
- infrastructure/runtime cost
- API/model cost
- total cost
- solved / failed / timeout / infrastructure-error outcome
- evaluator result and run identifier

Do not compare runs with materially different benchmark instances without reporting the difference.

## Primary metrics

### Solve rate

`solved / evaluated`

### Cost per solved task

`total_cost / solved`

If solved = 0, report the metric as undefined rather than assigning a value.

### Cost-normalized comparison

For a controlled comparison between configurations A and B, report:

- absolute solve-rate difference
- relative cost difference
- absolute cost-per-solved-task difference
- token difference
- retry difference
- latency difference

## Adoption rule

A Stewart optimization is accepted only when empirical evidence shows that it either:

1. lowers cost per solved task without a material solve-rate regression; or
2. materially improves solve rate for an explicitly accepted cost increase.

A benchmark result without independently verified evaluation is **NOT_PROVEN**.

## Initial experiment matrix

Start with a small reproducible subset before spending for a full benchmark:

| Track | Executor | Model | Benchmark |
|---|---|---|---|
| A | SWE-AF full build | baseline external model | SWE-bench Verified |
| B | SWE-AF `implement_issue` | same model | SWE-bench Verified |
| C | SWE-AF full build | low-cost candidate | SWE-bench Verified |
| D | SWE-AF `implement_issue` | low-cost candidate | SWE-bench Verified |

Use the same task subset for A-D.

Only after the subset produces valid end-to-end evidence should we scale to the full 500-instance Verified test set.

## Baseline integrity gate

Before model optimization:

- verify the official benchmark environment
- verify at least one gold patch using the official harness
- run one complete end-to-end Stewart task
- preserve the generated prediction/patch and evaluator output
- establish token/call/cost accounting

A failed infrastructure setup is not a model failure and must be classified separately.

## Evidence status

Current status:

- SWE-bench external harness: **AVAILABLE**
- SWE-bench Verified dataset: **AVAILABLE**
- Terminal-Bench external benchmark: **AVAILABLE**
- Stewart external execution: **NOT_PROVEN**
- Stewart cost-per-solved-task: **NOT_PROVEN**

