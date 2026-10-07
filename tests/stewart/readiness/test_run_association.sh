#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../stewart/readiness/repository-steward-readiness-run-association.sh"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sha=1111111111111111111111111111111111111111
make_response() {
 jq -n --arg sha "$sha" --arg state "$1" --argjson count "$2" --argjson more "$3" --argjson error "$4" '
 {errors: (if $error then [{message:"fixture error"}] else [] end),
 data:{repository:{object:{associatedPullRequests:{
 nodes:[range($count) | {number:(.+1),state:$state,headRefOid:$sha}],
 pageInfo:{hasNextPage:$more}}}}}}' > "$tmp"
}
make_response OPEN 1 false false
[[ "$(readiness_associate_run "$tmp" "$sha")" == 1 ]]
for spec in "CLOSED 1 false false" "OPEN 0 false false" "OPEN 2 false false" "OPEN 1 true false" "OPEN 1 false true"; do
 read -r state count more error <<< "$spec"
 make_response "$state" "$count" "$more" "$error"
 if readiness_associate_run "$tmp" "$sha"; then echo "unexpected association: $spec"; exit 1; fi
done
make_response OPEN 1 false false
if readiness_associate_run "$tmp" 2222222222222222222222222222222222222222; then exit 1; fi
echo "RUN_ASSOCIATION_MATRIX=PASS"
