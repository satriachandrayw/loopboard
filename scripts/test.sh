#!/usr/bin/env bash
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
UV=uv
need_bootstrap=1
if command -v uv >/dev/null 2>&1; then
  v="$(uv --version | awk '{print $2}')"
  if [ "$(printf '%s\n0.13.4\n' "$v" | sort -V | head -1)" = "0.13.4" ]; then need_bootstrap=0; fi
fi
if [ "$need_bootstrap" = 1 ]; then
  if [ ! -x "$LB_TMP/bin/uv" ]; then
    python3 -m pip install --quiet --target "$LB_TMP" uv==0.13.7
  fi
  UV="$LB_TMP/bin/uv"
fi
for pkg in worker connectors; do
  echo "== $pkg"
  (cd "$ROOT/$pkg" && "$UV" run --python 3.13 pytest -q)
done
if [ -f "$ROOT/web/package-lock.json" ]; then
  echo "== web"
  cd "$ROOT/web"
  npm ci --no-audit --no-fund
  npx vitest run
  npm run build
  echo "== built _headers"
  BUILT="$ROOT/worker/public/_headers"
  [ -f "$BUILT" ] || { echo "missing $BUILT after web build" >&2; exit 1; }
  cmp -s "$BUILT" "$ROOT/web/public/_headers" || { echo "built _headers differs from web/public/_headers" >&2; exit 1; }
  grep -qxF "  Content-Security-Policy: default-src 'self'; frame-ancestors 'none'" "$BUILT" \
    && grep -qxF "  X-Content-Type-Options: nosniff" "$BUILT" && grep -qxF "/*" "$BUILT" \
    || { echo "built _headers lacks CSP or nosniff for /*" >&2; exit 1; }
  echo "built _headers ok"
fi
