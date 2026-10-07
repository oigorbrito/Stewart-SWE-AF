#!/usr/bin/env bash
set -euo pipefail
source "${BASH_SOURCE[0]%/*}/repository-steward-readiness-classifier.sh"

readiness_classify_v2() {
  local base_decision
  base_decision="$(readiness_classify "$1" "$2" "$3" "$4" "$5")"
  if [[ "$base_decision" != READY_FOR_MERGE_CANDIDATE ]]; then
    printf '%s' "$base_decision"
    return
  fi
  case "$6" in
    APPROVED|NONE) printf '%s' READY_FOR_MERGE_CANDIDATE ;;
    CHANGES_REQUESTED|REVIEW_REQUIRED) printf '%s' NOT_READY_REVIEW ;;
    *) printf '%s' READINESS_UNKNOWN ;;
  esac
}

readiness_extract_v2() {
  jq -ser '
    if length != 1 then error("expected one response") else .[0] end
    | if type != "object" then error("invalid response") else . end
    | if (.errors == null or .errors == []) then . else error("GraphQL errors") end
    | .data.repository.pullRequest
    | if type != "object" then error("missing PR") else . end
    | if (has("state") and has("isDraft") and has("mergeStateStatus")
          and has("mergeable") and has("reviewDecision") and has("statusCheckRollup")
          and has("baseRefName") and has("headRefName") and has("headRefOid"))
      then . else error("missing requested field") end
    | if ((.state|type) == "string" and (.isDraft|type) == "boolean"
          and (.mergeStateStatus|type) == "string" and (.mergeable|type) == "string"
          and (.baseRefName|type) == "string" and (.headRefName|type) == "string"
          and (.headRefOid|type) == "string"
          and (.reviewDecision == null or (.reviewDecision|type) == "string")
          and (.statusCheckRollup == null or
               ((.statusCheckRollup|type) == "object" and
                (.statusCheckRollup|has("state")) and
                (.statusCheckRollup.state|type) == "string")))
      then . else error("invalid native field type") end
    | [.state, (.isDraft|tostring), .baseRefName, .headRefName, .headRefOid,
       .mergeable, .mergeStateStatus,
       (if .reviewDecision == null then "NONE"
        elif (.reviewDecision == "APPROVED" or .reviewDecision == "CHANGES_REQUESTED"
              or .reviewDecision == "REVIEW_REQUIRED") then .reviewDecision
        else "UNKNOWN" end),
       (if .statusCheckRollup == null then "NONE" else .statusCheckRollup.state end)]
    | @tsv
  ' "$1" 2>/dev/null
}

readiness_response_classify_v2() {
  local extracted state draft _base _head _head_sha mergeable merge_state review checks
  if ! extracted="$(readiness_extract_v2 "$1")"; then
    printf '%s' READINESS_UNKNOWN
    return
  fi
  IFS=$'\t' read -r state draft _base _head _head_sha mergeable merge_state review checks <<< "$extracted"
  readiness_classify_v2 "$state" "$draft" "$merge_state" "$mergeable" "$checks" "$review"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  if [[ "$#" -eq 2 && "$1" == --response ]]; then
    readiness_response_classify_v2 "$2"
  elif [[ "$#" -eq 6 ]]; then
    readiness_classify_v2 "$@"
  else
    echo "usage: $0 --response RESPONSE.json | STATE DRAFT MERGE_STATE MERGEABLE CHECKS REVIEW" >&2
    exit 2
  fi
fi
