#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
export TEST_DIR="$test_dir"
TEST_YQ=$(command -v yq)
real_sleep=$(command -v sleep)
export TEST_YQ
export PATH="$test_dir/bin:$PATH"
mkdir "$test_dir/bin"

cat >"$test_dir/bin/yq" <<'EOF'
#!/usr/bin/env bash
if [[ ${*: -1} == */katl/nodes.yaml ]]; then
  printf '%s\n' k8s-0 k8s-1 k8s-2
else
  exec "$TEST_YQ" "$@"
fi
EOF

cat >"$test_dir/bin/katlctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ ${*: -1} == --plan ]]; then
  echo "plan $3" >>"$TEST_DIR/actions"
  [[ ! -e $TEST_DIR/reject-plan ]] || exit 1
else
  echo "upgrade $3" >>"$TEST_DIR/actions"
  [[ ! -e $TEST_DIR/upgrade-fail ]] || exit 1
  if [[ -e $TEST_DIR/interrupt ]]; then
    kill -TERM "$PPID"
    exit 0
  fi
  if [[ -e $TEST_DIR/block-upgrade ]]; then
    touch "$TEST_DIR/upgrade-started"
    read -r _ <"$TEST_DIR/upgrade-gate"
  fi
  node=$3
  while [[ $1 != --version ]]; do shift; done
  echo "$2" >"$TEST_DIR/version-$node"
fi
EOF

cat >"$test_dir/bin/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == cnpg ]]; then
  [[ ${*: -1} == --request-timeout=30s ]]
  set -- "${@:1:$#-1}"
else
  [[ $1 == --request-timeout=30s ]]
  shift
fi
case "$*" in
  '-n monitoring create configmap katl-upgrade-lock '*)
    mkdir "$TEST_DIR/lock" 2>/dev/null || {
      echo 'Error from server (AlreadyExists): configmap already exists' >&2
      exit 1
    }
    echo test-lock-uid >"$TEST_DIR/lock/uid"
    for arg; do
      if [[ $arg == --from-literal=run-id=* ]]; then
        echo "${arg#--from-literal=run-id=}" >"$TEST_DIR/lock/run-id"
      fi
    done
    echo 'lock acquire' >>"$TEST_DIR/actions"
    if [[ -e $TEST_DIR/replace-lock ]]; then
      echo replacement-owner >"$TEST_DIR/lock/uid"
    fi
    if [[ -e $TEST_DIR/lost-create-response ]]; then
      echo 'Post "https://api.example": EOF' >&2
      exit 1
    fi
    echo test-lock-uid
    ;;
  '-n monitoring get configmap katl-upgrade-lock -o json')
    jq -nc --arg uid "$(cat "$TEST_DIR/lock/uid")" --arg run_id "$(cat "$TEST_DIR/lock/run-id" 2>/dev/null || true)" \
      '{metadata:{uid:$uid},data:{"run-id":$run_id}}'
    ;;
  '-n monitoring get configmap katl-upgrade-lock --ignore-not-found -o name')
    if [[ -d $TEST_DIR/lock ]]; then echo configmap/katl-upgrade-lock; fi
    ;;
  'delete --raw /api/v1/namespaces/monitoring/configmaps/katl-upgrade-lock '*)
    uid=$(jq -er '.preconditions.uid')
    if [[ ! -d $TEST_DIR/lock ]]; then
      echo 'Error from server (NotFound): configmap not found' >&2
      exit 1
    fi
    [[ $(cat "$TEST_DIR/lock/uid") == "$uid" ]] || exit 1
    rm -r "$TEST_DIR/lock"
    echo 'lock release' >>"$TEST_DIR/actions"
    if [[ -e $TEST_DIR/lost-delete-response ]]; then
      echo 'Delete "https://api.example": EOF' >&2
      exit 1
    fi
    ;;
  'get node/'*)
    if [[ -e $TEST_DIR/fail ]]; then
      echo 'forbidden' >>"$TEST_DIR/rejected"
      echo 'Error from server (Forbidden): nodes is forbidden' >&2
      exit 1
    fi
    node=${2#node/}
    version=$(cat "$TEST_DIR/version-$node")
    cordoned=false
    if [[ -e $TEST_DIR/cordoned-$node ]]; then cordoned=true; fi
    printf '{"spec":{"unschedulable":%s},"status":{"nodeInfo":{"osImage":"KatlOS %s"}}}\n' "$cordoned" "$version"
    ;;
  'get cephclusters.ceph.rook.io -A -o json')
    echo '{"items":[{"metadata":{"namespace":"rook-ceph","name":"ceph"},"status":{"phase":"Ready","ceph":{"health":"HEALTH_OK"}}}]}'
    ;;
  '-n rook-ceph exec deploy/rook-ceph-tools -- ceph status --format json')
    echo '{"health":{"status":"HEALTH_OK"},"osdmap":{"num_osds":3,"num_up_osds":3,"num_in_osds":3},"pgmap":{"num_pgs":1,"pgs_by_state":[{"state_name":"active+clean"}]}}'
    ;;
  'get clusters.postgresql.cnpg.io -A -o json')
    echo '{"items":[{"metadata":{"namespace":"db","name":"db"},"spec":{"instances":1},"status":{"phase":"Cluster in healthy state","readyInstances":1,"instancesStatus":{"healthy":["db-1"]},"currentPrimary":"db-1","targetPrimary":"db-1","conditions":[{"type":"Ready","status":"True"}]}}]}'
    ;;
  'get backups.postgresql.cnpg.io -A -o json') echo '{"items":[]}' ;;
  '-n db exec db-1 -c postgres -- psql '*) echo '' ;;
  '-n db get pods -l cnpg.io/cluster=db -o json')
    echo '{"items":[{"metadata":{"name":"db-1"},"spec":{"nodeName":"database-worker"}}]}'
    ;;
  'wait '*) ;;
  'apply -f -')
    payload=$("$TEST_YQ" -o=json -I=0 '.' | jq -s .)
    jq -e 'length == 1 and all(.[];
      .apiVersion == "observability.giantswarm.io/v1alpha2" and
      .kind == "Silence" and .metadata.namespace == "monitoring" and
      (.metadata.annotations["valid-until"] | fromdateiso8601) > now)
      and .[0].metadata.name == "katl-upgrade"
      and .[0].spec.matchers == [{name:"alertname",matchType:"=~",
        value:"PostgresReplicationMissing|etcdHighNumberOfLeaderChanges"},
        {name:"namespace",matchType:"=~",value:"database|kube-system"}]' <<<"$payload" >/dev/null
    duration=$(jq -r '((.[0].metadata.annotations["valid-until"] | fromdateiso8601) - now) / 60 | round' <<<"$payload")
    if [[ -e $TEST_DIR/retry-apply ]]; then
      mv "$TEST_DIR/retry-apply" "$TEST_DIR/retry-apply-input"
      echo "$payload" >"$TEST_DIR/retry-apply-input"
      echo 'Unable to connect to the server: connection reset by peer' >&2
      exit 1
    fi
    if [[ -e $TEST_DIR/retry-apply-input ]]; then
      cmp "$TEST_DIR/retry-apply-input" <(echo "$payload")
      rm "$TEST_DIR/retry-apply-input"
    fi
    echo "silence apply $duration" >>"$TEST_DIR/actions"
    echo "$payload" >"$TEST_DIR/silence"
    count=$(cat "$TEST_DIR/apply-count")
    echo "$((count + 1))" >"$TEST_DIR/apply-count"
    [[ ! -e $TEST_DIR/silence-fail ]] || exit 1
    [[ $((count + 1)) != "$(cat "$TEST_DIR/fail-apply-number")" ]] || exit 1
    ;;
  'delete --ignore-not-found --timeout=2m -f '*)
    [[ ${*: -1} == */.taskfiles/Katl/silences.yaml ]]
    echo 'silence delete' >>"$TEST_DIR/actions"
    rm -f "$TEST_DIR/silence"
    ;;
  'uncordon '*)
    if [[ -e $TEST_DIR/retry-uncordon || -e $TEST_DIR/fail-uncordon ]]; then
      rm -f "$TEST_DIR/retry-uncordon"
      echo 'uncordon transport error' >>"$TEST_DIR/actions"
      echo 'Unable to connect to the server: dial tcp: connect: connection refused' >&2
      exit 1
    fi
    echo "kubectl $*" >>"$TEST_DIR/actions"
    ;;
  'drain '*|'cnpg '*) echo "kubectl $*" >>"$TEST_DIR/actions" ;;
  *) echo "Unexpected kubectl call: $*" >&2; exit 1 ;;
esac
EOF

cat >"$test_dir/bin/kubectl-cnpg" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$test_dir/bin/sleep" <<'EOF'
#!/usr/bin/env bash
if [[ -e $TEST_DIR/allow-retries && $1 =~ ^(1|2|4)$ ]]; then
  echo "retry delay $1" >>"$TEST_DIR/retries"
  exit 0
fi
echo "Unexpected sleep: $*" >&2
exit 1
EOF
chmod +x "$test_dir/bin/"*

reset_run() {
  : >"$test_dir/actions"
  : >"$test_dir/retries"
  echo 0 >"$test_dir/apply-count"
  echo 0 >"$test_dir/fail-apply-number"
}

expect_failure() {
  if bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" "${1:-2026.10.1}"; then
    echo 'Expected the upgrade to fail' >&2
    exit 1
  fi
}

assert_count() {
  local count
  count=$(jq -Rn --arg pattern "$2" '[inputs | select(test($pattern))] | length' <"$test_dir/actions")
  test "$count" -eq "$1"
}

for node in k8s-0 k8s-1 k8s-2; do
  echo 2026.10.1 >"$test_dir/version-$node"
done
reset_run

# No-op runs may take the lock, but must not create or extend a silence.
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
printf '%s\n' 'lock acquire' 'lock release' >"$test_dir/noop"
diff -u "$test_dir/noop" "$test_dir/actions"

# A different release sharing the target prefix must still upgrade exactly once.
reset_run
echo 2026.10.10 >"$test_dir/version-k8s-1"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
cat >"$test_dir/expected" <<'EOF'
lock acquire
plan k8s-1
silence apply 120
silence apply 120
kubectl drain k8s-1 --ignore-daemonsets --delete-emptydir-data --force --timeout=20m
upgrade k8s-1
kubectl uncordon k8s-1
silence apply 20
lock release
EOF
diff -u "$test_dir/expected" "$test_dir/actions"
cp "$test_dir/silence" "$test_dir/prior-silence"
reset_run
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1
diff -u "$test_dir/noop" "$test_dir/actions"
cmp "$test_dir/prior-silence" "$test_dir/silence"

# A subsequent upgrade train renews the same resource for all three nodes.
reset_run
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.2
assert_count 3 '^plan '
assert_count 3 '^upgrade '
assert_count 6 '^silence apply 120$'
assert_count 1 '^silence apply 20$'
assert_count 0 '^silence delete$'
test ! -d "$test_dir/lock"

# Releasing a lock must not delete an object recreated with another UID.
reset_run
touch "$test_dir/replace-lock"
expect_failure 2026.10.2
test "$(cat "$test_dir/lock/uid")" == replacement-owner
assert_count 0 '^silence '
rm -r "$test_dir/lock"
rm "$test_dir/replace-lock"

# Retrying an incomplete train skips completed nodes and reuses an expired CR.
jq '.[0].metadata.annotations["valid-until"] = (now - 3600 | strftime("%Y-%m-%dT%H:%M:%SZ"))' \
  "$test_dir/silence" >"$test_dir/expired"
mv "$test_dir/expired" "$test_dir/silence"
echo 2026.10.1 >"$test_dir/version-k8s-1"
reset_run
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.2
assert_count 1 '^plan k8s-1$'
assert_count 1 '^upgrade k8s-1$'
assert_count 0 '^silence delete$'

# An unreadable node must stop the run before any disruptive operation.
reset_run
cp "$test_dir/silence" "$test_dir/prior-silence"
touch "$test_dir/fail"
expect_failure
diff -u "$test_dir/noop" "$test_dir/actions"
cmp "$test_dir/prior-silence" "$test_dir/silence"
test "$(wc -l <"$test_dir/rejected")" -eq 1

# Rejected upgrade plans must not cancel a previous successful run's grace period.
rm "$test_dir/fail"
touch "$test_dir/reject-plan"
reset_run
expect_failure 2026.10.3
assert_count 0 '^silence '
cmp "$test_dir/prior-silence" "$test_dir/silence"
rm "$test_dir/reject-plan"

# The retry path replays request bodies and recovers lost lock responses.
reset_run
touch "$test_dir/allow-retries" "$test_dir/lost-create-response" "$test_dir/lost-delete-response" \
  "$test_dir/retry-apply" "$test_dir/retry-uncordon"
echo 2026.10.10 >"$test_dir/version-k8s-1"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.2
assert_count 1 '^lock acquire$'
assert_count 1 '^lock release$'
assert_count 1 '^upgrade k8s-1$'
assert_count 1 '^kubectl uncordon k8s-1$'
assert_count 2 '^silence apply 120$'
test "$(wc -l <"$test_dir/retries")" -eq 4
test ! -d "$test_dir/lock"
test ! -e "$test_dir/retry-apply-input"
rm "$test_dir/lost-create-response" "$test_dir/lost-delete-response"

# Persistent transport failures stop at the retry limit without advancing nodes.
reset_run
touch "$test_dir/fail-uncordon"
echo 2026.10.10 >"$test_dir/version-k8s-1"
echo 2026.10.10 >"$test_dir/version-k8s-2"
expect_failure 2026.10.2
assert_count 4 '^uncordon transport error$'
assert_count 1 '^upgrade k8s-1$'
assert_count 0 '^upgrade k8s-2$'
test "$(wc -l <"$test_dir/retries")" -eq 3
rm "$test_dir/fail-uncordon" "$test_dir/allow-retries"

# A retry must surface a cordoned node even when the installed version matches.
reset_run
touch "$test_dir/cordoned-k8s-1"
expect_failure 2026.10.2
diff -u "$test_dir/noop" "$test_dir/actions"
rm "$test_dir/cordoned-k8s-1"

# Silence creation must succeed before any drain or node upgrade.
for node in k8s-0 k8s-2; do echo 2026.10.1 >"$test_dir/version-$node"; done
echo 2026.10.10 >"$test_dir/version-k8s-1"
reset_run
touch "$test_dir/silence-fail"
expect_failure
printf '%s\n' 'lock acquire' 'plan k8s-1' 'silence apply 120' 'silence delete' 'lock release' >"$test_dir/expected"
diff -u "$test_dir/expected" "$test_dir/actions"

# A failed upgrade removes its silence immediately and leaves the node cordoned.
rm "$test_dir/silence-fail"
touch "$test_dir/upgrade-fail"
reset_run
expect_failure
cat >"$test_dir/expected" <<'EOF'
lock acquire
plan k8s-1
silence apply 120
silence apply 120
kubectl drain k8s-1 --ignore-daemonsets --delete-emptydir-data --force --timeout=20m
upgrade k8s-1
silence delete
lock release
EOF
diff -u "$test_dir/expected" "$test_dir/actions"

# Interruptions must also expire the silence and preserve the signal exit code.
rm "$test_dir/upgrade-fail"
touch "$test_dir/interrupt"
reset_run
result=0
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1 || result=$?
test "$result" -eq 143
diff -u "$test_dir/expected" "$test_dir/actions"
rm "$test_dir/interrupt"

# Failed renewal before draining stops disruption and cancels the silence.
reset_run
echo 2 >"$test_dir/fail-apply-number"
expect_failure
assert_count 0 '^kubectl drain '
assert_count 1 '^silence delete$'
test ! -d "$test_dir/lock"

# Failure to apply the grace period is an error, with silence cleanup.
reset_run
echo 3 >"$test_dir/fail-apply-number"
expect_failure
assert_count 1 '^upgrade '
assert_count 1 '^silence delete$'
test ! -d "$test_dir/lock"

# A stale lock cannot be stolen or removed by a new invocation.
reset_run
mkdir "$test_dir/lock"
echo another-owner >"$test_dir/lock/uid"
test ! -e "$test_dir/silence"
expect_failure
test ! -s "$test_dir/actions"
test "$(cat "$test_dir/lock/uid")" == another-owner
test ! -e "$test_dir/silence"
rm -r "$test_dir/lock"

# A second process cannot affect the silence while the first is upgrading.
reset_run
echo 2026.10.10 >"$test_dir/version-k8s-1"
touch "$test_dir/block-upgrade"
mkfifo "$test_dir/upgrade-gate"
bash "$root/.taskfiles/Katl/scripts/upgrade-cluster.sh" 2026.10.1 &
first_run=$!
for ((attempt = 0; attempt < 200; attempt++)); do
  [[ ! -e $test_dir/upgrade-started ]] || break
  "$real_sleep" 0.05
done
test -e "$test_dir/upgrade-started"
cp "$test_dir/actions" "$test_dir/first-actions"
cp "$test_dir/silence" "$test_dir/prior-silence"
expect_failure
cmp "$test_dir/actions" "$test_dir/first-actions"
cmp "$test_dir/silence" "$test_dir/prior-silence"
echo continue >"$test_dir/upgrade-gate"
wait "$first_run"
test ! -d "$test_dir/lock"
