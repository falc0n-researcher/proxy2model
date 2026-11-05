#!/usr/bin/env bash
# One command from a fresh clone, no install and no network:
# model four recorded OWASP Juice Shop sessions (anonymous, user, accounting, admin), show what
# anonymous reached compared with a signed-in user, show what signing in added, and open the report.
# Usage: ./demo.sh [output-dir]
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="${1:-proxy2model-out}"
export PROXY2MODEL_OFFLINE=1

py=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    py="$c"; break
  fi
done
run() {
  if command -v proxy2model >/dev/null 2>&1; then proxy2model "$@"
  elif [ -n "$py" ]; then PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}" "$py" -m proxy2model "$@"
  else echo "proxy2model needs Python 3.10 or newer" >&2; exit 2
  fi
}
step() { printf '\n\033[1;38;5;202m//\033[0m \033[1m%s\033[0m\n' "$1"; }

step "build: four recorded sessions of OWASP Juice Shop, one role each"
run "$here/samples/juiceshop-anon.xml" -w juiceshop --role anon --fresh --label demo-anon --out "$out" >/dev/null
echo "  anon        built"
run "$here/samples/juiceshop-user.xml" -w juiceshop --role user --label demo-user --out "$out" >/dev/null
echo "  user        built"
for r in accountant admin; do
  run "$here/samples/juiceshop-$r.xml" -w juiceshop --role "$r" --out "$out" >/dev/null
  printf '  %-11s built\n' "$r"
done

step "cross-role: what anonymous reached, compared with a signed-in user"
run cross-role juiceshop --low anon --high user --out "$out" | head -n 22
echo "  ... (proxy2model cross-role juiceshop --low anon --high user --all)"

step "diff: what signing in added to the app's surface"
run diff juiceshop demo-anon demo-user --out "$out" | head -n 9

report="$out/juiceshop/report.html"
step "report: $report"
case "$(uname -s)" in
  Darwin) open "$report" ;;
  Linux)  xdg-open "$report" >/dev/null 2>&1 || true ;;
  *)      echo "  open it in a browser" ;;
esac
