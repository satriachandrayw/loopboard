#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR=/tmp/lb-uv-cache UV_PYTHON_INSTALL_DIR=/tmp/lb-uv-py npm_config_cache=/tmp/lb-npm-cache
UV=uv
need_bootstrap=1
if command -v uv >/dev/null 2>&1; then
  v="$(uv --version | awk '{print $2}')"
  if [ "$(printf '%s\n0.13.4\n' "$v" | sort -V | head -1)" = "0.13.4" ]; then need_bootstrap=0; fi
fi
if [ "$need_bootstrap" = 1 ]; then
  if [ ! -x /tmp/lb-uv/bin/uv ]; then
    python3 -m pip install --quiet --target /tmp/lb-uv uv==0.13.7
  fi
  UV=/tmp/lb-uv/bin/uv
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
fi
