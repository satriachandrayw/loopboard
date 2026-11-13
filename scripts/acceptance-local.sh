#!/usr/bin/env bash
# Local stack check for v1a. Exits 0 only when every check passes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LB_TMP="${LB_TMP_DIR:-/tmp/lb-uv-$(id -u)}"
if [ -e "$LB_TMP" ] && [ ! -O "$LB_TMP" ]; then
  echo "refusing to use $LB_TMP: it is owned by another user" >&2
  exit 1
fi
if [ -L "$LB_TMP" ]; then
  echo "refusing to use $LB_TMP: it is a symlink" >&2
  exit 1
fi
mkdir -p "$LB_TMP"
chmod 700 "$LB_TMP"
export UV_CACHE_DIR="$LB_TMP/cache" UV_PYTHON_INSTALL_DIR="$LB_TMP/py" npm_config_cache="$LB_TMP/npm"
export XDG_CONFIG_HOME="$LB_TMP/xdg" WRANGLER_SEND_METRICS=false
need_bootstrap=1
if command -v uv >/dev/null 2>&1; then
  v="$(uv --version | awk '{print $2}')"
  if [ "$(printf '%s\n0.13.4\n' "$v" | sort -V | head -1)" = "0.13.4" ]; then need_bootstrap=0; fi
fi
if [ "$need_bootstrap" = 1 ] && [ ! -x "$LB_TMP/bin/uv" ]; then
  python3 -m pip install --quiet --target "$LB_TMP" uv==0.13.7
fi
export PATH="$LB_TMP/bin:$PATH"

PORT=8799
BASE="http://localhost:$PORT"
TMP="$(mktemp -d)"
DEV_PID=""
FAILED=0
cleanup() {
  if [ -n "$DEV_PID" ]; then
    kill -- "-$DEV_PID" 2>/dev/null || kill "$DEV_PID" 2>/dev/null || true
    sleep 1
    pkill -f "workerd.*$TMP" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap cleanup EXIT

ok() { echo "ok   $*"; }
fail() { echo "FAIL $*"; FAILED=1; }
check() { # check <label> <command...>
  local label="$1"; shift
  if "$@"; then ok "$label"; else fail "$label"; fi
}
jget() { python3 -c "import sys,json; d=json.load(sys.stdin); print($1)"; }

echo "== build web"
(cd "$ROOT/web" && npm ci --no-audit --no-fund >"$TMP/npm.log" 2>&1 && npm run build >>"$TMP/npm.log" 2>&1) \
  || { tail -20 "$TMP/npm.log"; echo "FAIL web build"; exit 1; }
ok "web build"

STATE="$TMP/state"
cd "$ROOT/worker"
echo "== migrations (fresh local D1 in temp dir)"
npx wrangler d1 migrations apply loopboard --local --persist-to "$STATE" >"$TMP/mig.log" 2>&1 \
  || { tail -20 "$TMP/mig.log"; echo "FAIL migrations"; exit 1; }
ok "migrations applied"

mk_token() { # mk_token <name> <scopes> [source] -> sets TOKEN_OUT, inserts row
  local out sql
  out="$(uv run --python 3.13 python scripts/make_token.py --name "$1" --scopes "$2" ${3:+--source "$3"})"
  TOKEN_OUT="$(printf '%s\n' "$out" | sed -n 's/^TOKEN=//p')"
  sql="$(printf '%s\n' "$out" | grep '^INSERT')"
  npx wrangler d1 execute loopboard --local --persist-to "$STATE" --command "$sql" >"$TMP/tok.log" 2>&1 \
    || { tail -10 "$TMP/tok.log"; return 1; }
}
mk_token acceptance-rw read,write; RW="$TOKEN_OUT"
mk_token acceptance-ingest ingest kanban; export LB_INGEST_TOKEN="$TOKEN_OUT"
ok "tokens created"

echo "== dev server"
setsid uv run --python 3.13 pywrangler dev --port "$PORT" --test-scheduled --persist-to "$STATE" \
  >"$TMP/dev.log" 2>&1 &
DEV_PID=$!
code=000
for _ in $(seq 1 120); do
  if ! kill -0 "$DEV_PID" 2>/dev/null; then echo "     dev server exited"; break; fi
  code="$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $RW" "$BASE/api/health" || true)"
  [ "$code" = 200 ] && break
  sleep 1
done
if [ "$code" != 200 ]; then
  tail -30 "$TMP/dev.log"
  echo "FAIL 3 dev server /api/health (last HTTP $code)"
  exit 1
fi
ok "3 /api/health with read token -> 200"

api() { # api <method> <path> [json]
  curl -s -X "$1" -H "Authorization: Bearer $RW" -H 'Content-Type: application/json' \
    ${3:+-d "$3"} -w '\n%{http_code}' "$BASE$2"
}

r="$(api POST /api/projects '{"key":"DEMO","name":"Demo"}')"
[ "${r##*$'\n'}" = 201 ] && ok "4 POST /api/projects -> 201" || fail "4 POST /api/projects -> ${r##*$'\n'}"

cat >"$TMP/config.toml" <<CFG
[loopboard]
url = "$BASE"
token_env = "LB_INGEST_TOKEN"

[general]
human = "owner"

[kanban.tenants]
demo = "DEMO"
CFG
set +e
SUMMARY="$(cd "$ROOT/connectors" && uv run --python 3.13 loopboard sync kanban --config "$TMP/config.toml" \
  --cli-replay "$ROOT/connectors/tests/fixtures/kanban" | tail -1)"
RC=$?
set -e
echo "     sync summary: $SUMMARY"
if [ "$RC" = 0 ] && printf '%s' "$SUMMARY" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d['collected']==8 and d['accepted']==8 else 1)"; then
  ok "5 sync kanban exit 0, collected 8, accepted 8"
else
  fail "5 sync kanban (exit $RC)"
fi

# R3: create epic DEMO-E1, file every unfiled item to it, compare board counts.
# Step 6 runs without set -e so any failure prints FAIL instead of exiting silently.
set +e
EXPECTED="$ROOT/connectors/tests/fixtures/kanban/expected-board.json"
r="$(api POST /api/projects/DEMO/epics '{"title":"Acceptance epic","goal":"Acceptance goal.","waiting_on":"human:owner"}')"
[ "${r##*$'\n'}" = 201 ] || fail "6 create epic -> ${r##*$'\n'}"
EPIC="$(printf '%s' "${r%$'\n'*}" | jget "d['key']" 2>/dev/null || echo "")"
if [ "$EPIC" != "DEMO-E1" ]; then fail "6 epic key is '$EPIC', expected DEMO-E1"; fi
IDS="$(api GET /api/unfiled | sed '$d' | jget "' '.join(str(i['id']) for i in d)")" \
  || { fail "6 GET /api/unfiled"; IDS=""; }
WANT_UNFILED="$(jget "d['unfiled']" <"$EXPECTED")"
N_UNFILED="$(echo $IDS | wc -w)"
[ "$N_UNFILED" = "$WANT_UNFILED" ] && ok "6 /api/unfiled count $N_UNFILED matches expected-board.json" \
  || fail "6 /api/unfiled count $N_UNFILED, expected $WANT_UNFILED"
for id in $IDS; do
  r="$(api POST "/api/items/$id/filing" "{\"filing\":\"epic\",\"epic_key\":\"DEMO-E1\"}")"
  [ "${r##*$'\n'}" = 200 ] || fail "6 file item $id -> ${r##*$'\n'}"
done
echo "     filed $N_UNFILED items to DEMO-E1"
BOARD="$(api GET /api/board | sed '$d')"
printf '%s' "$BOARD" >"$TMP/board.json"
if python3 - "$TMP/board.json" "$EXPECTED" <<'PY'
import json, sys
board = json.load(open(sys.argv[1]))
want = json.load(open(sys.argv[2]))["board"]
got = {c["column"]: c["count"] for c in board["columns"]}
print("     board counts:", got)
sys.exit(0 if got == want else 1)
PY
then ok "6 /api/board column counts match expected-board.json"; else fail "6 /api/board column counts differ from expected-board.json"; fi
set -e

# 6b: update an existing item on real D1, then replay an older timestamp (skipped_older).
set +e
ING_BASE="$(cd "$ROOT/connectors" && uv run --python 3.13 python - "$ROOT/connectors/tests/fixtures/kanban" <<'PY'
import json, sys
from loopboard_connectors import kanban
items = kanban.collect(kanban.replay_runner(sys.argv[1]), human="owner", tenants={"demo": "DEMO"}, board=None)
print(json.dumps(items[0].to_payload()))
PY
)"
UPD_ID="$(printf '%s' "$ING_BASE" | jget "d['external_id']" 2>/dev/null)"
NEW_TITLE="Acceptance updated title"
ts_ago() { python3 -c "import datetime as d; print((d.datetime.now(d.timezone.utc)-d.timedelta(minutes=$1)).strftime('%Y-%m-%dT%H:%M:%SZ'))"; }
ing_post() { # ing_post <last_activity_at> <title> -> response body
  local body
  body="$(printf '%s' "$ING_BASE" | python3 -c "import sys,json; d=json.load(sys.stdin); d['last_activity_at']=sys.argv[1]; d['title']=sys.argv[2]; print(json.dumps({'source':'kanban','items':[d]}))" "$1" "$2")"
  curl -s -X POST -H "Authorization: Bearer $LB_INGEST_TOKEN" -H 'Content-Type: application/json' -d "$body" "$BASE/api/ingest"
}
r="$(ing_post "$(ts_ago 1)" "$NEW_TITLE")"
[ "$(printf '%s' "$r" | jget "d['updated']" 2>/dev/null)" = 1 ] \
  && ok "6b ingest update of $UPD_ID -> updated == 1" || fail "6b ingest update -> $r"
r="$(ing_post "$(ts_ago 120)" "Older title must not win")"
[ "$(printf '%s' "$r" | jget "d['skipped_older']" 2>/dev/null)" = 1 ] \
  && ok "6b ingest older timestamp -> skipped_older == 1" || fail "6b ingest older -> $r"
DETAIL="$(api GET /api/epics/DEMO-E1 | sed '$d')"
printf '%s' "$DETAIL" >"$TMP/detail.json"
if python3 - "$TMP/detail.json" "$UPD_ID" "$NEW_TITLE" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
ts = [t for g in d["tasks"].values() for t in g if t["external_id"] == sys.argv[2]]
assert ts and ts[0]["title"] == sys.argv[3], ts
assert any(e["kind"] == "item.updated" for e in d["events"]), "no item.updated event"
PY
then ok "6b epic detail shows new title and an item.updated event"; else fail "6b epic detail after update"; fi
set -e

code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/board")"
[ "$code" = 401 ] && ok "6 /api/board without token -> 401" || fail "6 /api/board without token -> $code"

code="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/cdn-cgi/handler/scheduled?cron=*/15+*+*+*+*")"
[ "$code" = 200 ] && ok "7 scheduled handler -> 200" || fail "7 scheduled handler -> $code"

t="$(curl -s -o /dev/null -w '%{time_total}' -H "Authorization: Bearer $RW" "$BASE/api/board")"
echo "     warm /api/board: ${t}s (informational; cold start and D1 free-tier usage unmeasured)"

if [ "$FAILED" = 0 ]; then
  echo "ACCEPTANCE PASS"
else
  echo "ACCEPTANCE FAIL"
  tail -20 "$TMP/dev.log" || true
  exit 1
fi
