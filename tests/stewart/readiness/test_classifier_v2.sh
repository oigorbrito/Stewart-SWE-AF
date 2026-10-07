#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../stewart/readiness/repository-steward-readiness-classifier-v2.sh"
readiness_classifier_self_test

assert_v2() {
  local expected="$1" actual
  shift
  actual="$(readiness_classify_v2 "$@")"
  [[ "$actual" == "$expected" ]] || { echo "v2 mismatch: expected=$expected actual=$actual inputs=$*" >&2; exit 1; }
}
assert_v2 READY_FOR_MERGE_CANDIDATE OPEN false CLEAN MERGEABLE SUCCESS NONE
assert_v2 READY_FOR_MERGE_CANDIDATE OPEN false CLEAN MERGEABLE SUCCESS APPROVED
assert_v2 NOT_READY_REVIEW OPEN false CLEAN MERGEABLE SUCCESS CHANGES_REQUESTED
assert_v2 NOT_READY_REVIEW OPEN false CLEAN MERGEABLE SUCCESS REVIEW_REQUIRED
for review in UNKNOWN null unexpected ""; do
  assert_v2 READINESS_UNKNOWN OPEN false CLEAN MERGEABLE SUCCESS "$review"
done
assert_v2 NOT_READY_STATE CLOSED false CLEAN MERGEABLE SUCCESS APPROVED
assert_v2 NOT_READY_DRAFT OPEN true CLEAN MERGEABLE SUCCESS CHANGES_REQUESTED
assert_v2 READINESS_UNKNOWN OPEN UNKNOWN CLEAN MERGEABLE SUCCESS APPROVED
assert_v2 READINESS_UNKNOWN OPEN null CLEAN MERGEABLE SUCCESS APPROVED
assert_v2 NOT_READY_CONFLICT OPEN false DIRTY CONFLICTING SUCCESS CHANGES_REQUESTED
assert_v2 NOT_READY_CONFLICT OPEN false CLEAN CONFLICTING SUCCESS APPROVED
assert_v2 NOT_READY_BLOCKED OPEN false BLOCKED MERGEABLE SUCCESS APPROVED
assert_v2 NOT_READY_BEHIND OPEN false BEHIND MERGEABLE SUCCESS APPROVED
assert_v2 NOT_READY_CHECKS OPEN false CLEAN MERGEABLE PENDING CHANGES_REQUESTED
assert_v2 NOT_READY_CHECKS OPEN false CLEAN MERGEABLE NONE NONE
assert_v2 NOT_READY_CHECKS OPEN false UNSTABLE MERGEABLE SUCCESS APPROVED
assert_v2 READINESS_UNKNOWN OPEN false UNKNOWN UNKNOWN SUCCESS APPROVED
assert_v2 READINESS_UNKNOWN OPEN false CLEAN UNKNOWN SUCCESS APPROVED

task_dir="$(mktemp -d)"
trap 'rm -rf "$task_dir"' EXIT
fixture="$task_dir/response.json"
base_response='{"data":{"repository":{"pullRequest":{"state":"OPEN","isDraft":false,"mergeStateStatus":"CLEAN","mergeable":"MERGEABLE","reviewDecision":null,"statusCheckRollup":{"state":"SUCCESS"},"baseRefName":"main","headRefName":"fixture","headRefOid":"0123456789012345678901234567890123456789"}}}}'
assert_response() {
  local expected="$1" mutation="$2" actual
  printf '%s' "$base_response" | jq "$mutation" > "$fixture"
  actual="$(readiness_response_classify_v2 "$fixture")"
  [[ "$actual" == "$expected" ]] || { echo "response mismatch: expected=$expected actual=$actual mutation=$mutation" >&2; exit 1; }
}
assert_response READY_FOR_MERGE_CANDIDATE '.'
assert_response READY_FOR_MERGE_CANDIDATE '.errors=[] | .data.repository.pullRequest.reviewDecision="APPROVED"'
assert_response NOT_READY_REVIEW '.data.repository.pullRequest.reviewDecision="CHANGES_REQUESTED"'
assert_response NOT_READY_REVIEW '.data.repository.pullRequest.reviewDecision="REVIEW_REQUIRED"'
assert_response READINESS_UNKNOWN 'del(.data.repository.pullRequest.reviewDecision)'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.reviewDecision="NONE"'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.reviewDecision="UNRECOGNIZED"'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.reviewDecision={}'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.reviewDecision=false'
assert_response READINESS_UNKNOWN '.errors=[{"message":"partial query failure"}]'
assert_response READINESS_UNKNOWN '.errors={}'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest=null'
assert_response READINESS_UNKNOWN 'del(.data.repository.pullRequest.isDraft)'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.isDraft="false"'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.statusCheckRollup={}'
assert_response READINESS_UNKNOWN 'del(.data.repository.pullRequest.statusCheckRollup)'
assert_response NOT_READY_CHECKS '.data.repository.pullRequest.statusCheckRollup=null'
assert_response NOT_READY_CHECKS '.data.repository.pullRequest.statusCheckRollup.state="PENDING"'
assert_response READINESS_UNKNOWN '.data.repository.pullRequest.mergeable="UNKNOWN"'
assert_response NOT_READY_DRAFT '.data.repository.pullRequest.isDraft=true | .data.repository.pullRequest.reviewDecision="CHANGES_REQUESTED"'
printf '{' > "$fixture"
[[ "$(readiness_response_classify_v2 "$fixture")" == READINESS_UNKNOWN ]]
printf '%s
%s
' "$base_response" "$base_response" > "$fixture"
[[ "$(readiness_response_classify_v2 "$fixture")" == READINESS_UNKNOWN ]]
echo "CLASSIFIER_V2_MATRIX=PASS"
