# Stewart operating evidence and promotion contract

This document carries forward the validated operating rules and evidence semantics from the first Stewart work into the final `Stewart-SWE-AF` product.

## Product boundary

`Stewart-SWE-AF` is the final SWE-AF product. Stewart is not a replacement for the SWE-AF execution engine.

- SWE-AF remains responsible for planning, DAG scheduling, parallel execution, worktrees, coding, QA, review, integration, verification, checkpoints, and adaptation.
- Stewart contributes the governance/evidence layer: evidence collection, readiness classification, acceptance, and promotion policy.
- `Stewart-harness` remains the evidence/test harness; it is not the final product.

The governing rule is:

> SWE-AF PASS does not by itself mean STEWART ACCEPTED.

A product promotion decision requires the required evidence gates to be satisfied.

## Evidence semantics

Evidence states are deliberately distinct:

```
IMPLEMENTED != EXECUTED != VERIFIED != ACCEPTED
```

- **IMPLEMENTED** — code or configuration exists.
- **EXECUTED** — the relevant procedure actually ran.
- **VERIFIED** — an independent or defined verifier established the expected result.
- **ACCEPTED** — the evidence satisfies the promotion policy.

Never promote a lower evidence state into a stronger one by inference.

## Authority boundary

The Stewart observer is READ/REPORT only.

### Allowed

- READ repository, pull request, workflow and check state.
- REPORT observations and evidence.
- Classify readiness from native GitHub state.

### Forbidden

The observer must not autonomously:

- merge or approve pull requests;
- request reviews;
- rerun checks;
- change repository rules;
- close issues;
- auto-merge;
- auto-release;
- delete branches.

Semantic LLM inference is not a qualified readiness signal. Native GitHub state is preferred.

## Readiness contract

The qualified positive readiness predicate is:

```text
state == OPEN
AND isDraft == false
AND mergeStateStatus == CLEAN
AND mergeable == MERGEABLE
AND statusCheckRollup.state == SUCCESS
=> READY_FOR_MERGE_CANDIDATE
```

`MERGE_STATE_STATUS_ALONE` is explicitly rejected as sufficient evidence.

Fail-closed behavior is required for unknown, missing, pending, conflicting, or otherwise inconclusive state.

## Closure observation contract

For issue closure observation, use GitHub's native `PullRequest.closingIssuesReferences` relationship.

A closure candidate requires:

```text
PR merged == true
AND base == default branch
AND an auto-detected closing reference exists
AND referenced issue is OPEN
=> CLOSURE_CANDIDATE
```

This observer reports the candidate; it does not close the issue.

## Provenance

The readiness/conformance material incorporated into the SWE-AF fork originated from the Stewart harness evidence chain:

- harness implementation/evidence state: `94056c2d...`
- imported Searchleads evidence state: `450243c4de7223db5d2e0b10de737de403520d3d`

The exact source SHA must be preserved when an implementation is promoted or refreshed.

## Promotion policy for SWE-AF changes

Upstream SWE-AF PRs and issues are **candidates**, not automatic dependencies.

For each candidate, Stewart should record one of:

- `REUSE`
- `ADAPT`
- `WRAP`
- `FORK`
- `CUSTOM`
- `REJECTED`
- `NOT_PROVEN`

Acceptance requires evidence appropriate to the change. In particular, changes that affect agent execution must eventually be evaluated on real software-engineering tasks, not only unit tests.

## Cost-first qualification

Cost is a first-class acceptance criterion.

For agent/runtime changes, measure at minimum:

- solve/pass rate;
- total input/output tokens when available;
- number of agent invocations;
- retries and replans;
- wall-clock latency;
- provider/model cost;
- failure mode.

A change should not be accepted merely because it passes the existing test suite. If it increases cost without improving solve rate, reliability, or another explicitly accepted property, the default disposition is rejection or `NOT_PROVEN`.

## Current SWE-AF gate

The current fork has established:

- Python suite: 1317 passed, 1 skipped;
- Go build/vet/tests with race detector: passed;
- readiness/conformance layer: passed.

These establish software and conformance gates, not real-agent effectiveness.

Still required for product qualification:

- reproducible benchmark checkout;
- real end-to-end SWE task execution;
- independently checkable solve rate;
- token/cost/retry evidence;
- controlled comparison of candidate runtimes/models.

## Known reproducibility debt

The repository contains the benchmark path:

`examples/agent-comparison/swe-af-minimax/todo-app-benchmark`

as a gitlink without a corresponding `.gitmodules` entry. GitHub Actions therefore emits:

```
fatal: No url found for submodule path
'examples/agent-comparison/swe-af-minimax/todo-app-benchmark'
in .gitmodules
```

This must be resolved before the benchmark is treated as reproducible evidence. The preferred resolution is whichever of these is empirically justified:

1. restore a valid recursive submodule definition and prove clean checkout;
2. convert the fixture into ordinary tracked repository content;
3. remove the stale benchmark gitlink if it is no longer part of the qualification path.

Do not label the benchmark VERIFIED until a clean checkout and repeatable execution succeed.

## Decision rule

The final product should converge on:

```
upstream candidate
    -> inspect
    -> adapt/isolate
    -> run controlled evidence
    -> compare solve rate + cost + reliability
    -> ACCEPT / REJECT / NOT_PROVEN
```

Upstream compatibility is useful, but empirical evidence and cost efficiency decide what enters `Stewart-SWE-AF`.
