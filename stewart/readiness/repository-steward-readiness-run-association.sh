#!/usr/bin/env bash
# Select a single current OPEN PR from GitHub-native commit associations.
readiness_associate_run() {
  local response="$1" head_sha="$2"
  [[ "$head_sha" =~ ^[0-9a-f]{40}$ ]] || return 1
  jq -er --arg sha "$head_sha" '
    select((.errors // []) | length == 0) |
    .data.repository.object.associatedPullRequests |
    select(.pageInfo.hasNextPage == false and (.nodes | type) == "array") |
    [.nodes[] | select(.state == "OPEN" and .headRefOid == $sha)] |
    select(length == 1) | .[0].number |
    select(type == "number" and . > 0 and floor == .)
  ' "$response"
}
