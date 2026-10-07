#!/usr/bin/env bash
set -euo pipefail

readiness_classify() {
  local state="$1"
  local draft="$2"
  local merge_state="$3"
  local mergeable="$4"
  local checks="$5"

  if [[ "$state" != "OPEN" ]]; then
    printf '%s' "NOT_READY_STATE"
  elif [[ "$draft" == "true" ]]; then
    printf '%s' "NOT_READY_DRAFT"
  elif [[ "$draft" != "false" ]]; then
    printf '%s' "READINESS_UNKNOWN"
  elif [[ "$merge_state" == "DIRTY" || "$mergeable" == "CONFLICTING" ]]; then
    printf '%s' "NOT_READY_CONFLICT"
  elif [[ "$merge_state" == "BLOCKED" ]]; then
    printf '%s' "NOT_READY_BLOCKED"
  elif [[ "$merge_state" == "BEHIND" ]]; then
    printf '%s' "NOT_READY_BEHIND"
  elif [[ "$merge_state" == "UNSTABLE" || "$checks" != "SUCCESS" ]]; then
    printf '%s' "NOT_READY_CHECKS"
  elif [[ "$merge_state" == "CLEAN" && "$mergeable" == "MERGEABLE" && "$checks" == "SUCCESS" ]]; then
    printf '%s' "READY_FOR_MERGE_CANDIDATE"
  else
    printf '%s' "READINESS_UNKNOWN"
  fi
}

readiness_assert_case() {
  local expected="$1"
  shift
  local actual
  actual="$(readiness_classify "$@")"
  if [[ "$actual" != "$expected" ]]; then
    echo "classifier test failed: expected=$expected actual=$actual inputs=$*" >&2
    return 1
  fi
}

readiness_classifier_self_test() {
  readiness_assert_case READY_FOR_MERGE_CANDIDATE OPEN false CLEAN MERGEABLE SUCCESS
  readiness_assert_case NOT_READY_STATE CLOSED false CLEAN MERGEABLE SUCCESS
  readiness_assert_case NOT_READY_DRAFT OPEN true CLEAN MERGEABLE SUCCESS
  readiness_assert_case READINESS_UNKNOWN OPEN UNKNOWN CLEAN MERGEABLE SUCCESS
  readiness_assert_case READINESS_UNKNOWN OPEN null CLEAN MERGEABLE SUCCESS
  readiness_assert_case NOT_READY_CONFLICT OPEN false DIRTY CONFLICTING SUCCESS
  readiness_assert_case NOT_READY_CONFLICT OPEN false CLEAN CONFLICTING SUCCESS
  readiness_assert_case NOT_READY_BLOCKED OPEN false BLOCKED MERGEABLE SUCCESS
  readiness_assert_case NOT_READY_BEHIND OPEN false BEHIND MERGEABLE SUCCESS
  readiness_assert_case NOT_READY_CHECKS OPEN false CLEAN MERGEABLE PENDING
  readiness_assert_case NOT_READY_CHECKS OPEN false CLEAN MERGEABLE NONE
  readiness_assert_case READINESS_UNKNOWN OPEN false UNKNOWN UNKNOWN SUCCESS
  readiness_assert_case READINESS_UNKNOWN OPEN false CLEAN UNKNOWN SUCCESS
  echo "CLASSIFIER_MATRIX=PASS"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "${1:-}" == "--self-test" ]]; then
    readiness_classifier_self_test
  elif [[ "$#" -eq 5 ]]; then
    readiness_classify "$@"
  else
    echo "usage: $0 --self-test | STATE DRAFT MERGE_STATE MERGEABLE CHECKS" >&2
    exit 2
  fi
fi
