#!/usr/bin/env bash
# Stage everything main.js expects at runtime: app/, runtime/ (portable Python), topp/.
set -euo pipefail
cd "$(dirname "$0")"

PYVER=${PYVER:-3.11}          # pyopenms and numpy 1.26.4 have no 3.13 wheels
OPENMS_BIN=${OPENMS_BIN:-}   # point at an OpenMS bin/ dir to bundle the TOPP tools

# The payload is this repo at HEAD; git archive keeps untracked files and .git out.
rm -rf app && mkdir app
# Not piped into tar: tar stops at the end-of-archive marker and closes the pipe
# while git is still writing its trailing padding, so pipefail sees SIGPIPE.
git -C .. archive HEAD -o "$PWD/app.tar"   # -o is relative to -C, so spell it out
tar -x -f app.tar -C app
rm app.tar
rm -rf app/desktop app/example-data   # 101 MB of samples, not worth shipping

if [ ! -d runtime ]; then
  # uv's managed interpreters bake in an absolute prefix and are not relocatable,
  # so pull the portable install_only build instead.
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64)    TRIPLE=aarch64-apple-darwin ;;
    Darwin-x86_64)   TRIPLE=x86_64-apple-darwin ;;
    Linux-x86_64)    TRIPLE=x86_64-unknown-linux-gnu ;;
    Linux-aarch64)   TRIPLE=aarch64-unknown-linux-gnu ;;
    MINGW*|MSYS*|CYGWIN*) TRIPLE=x86_64-pc-windows-msvc ;;
    *) echo "unsupported platform: $(uname -sm)" >&2; exit 1 ;;
  esac
  # Anonymous api.github.com is rate limited per IP, which CI runners share, so
  # authenticate when a token is around. The failure is a JSON error object with
  # no "assets" key, hence the explicit check below.
  AUTH=()
  [ -n "${GITHUB_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")
  curl -sS "${AUTH[@]}" https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest -o pbs.json
  URL=$(python3 -c "
import json,sys
d=json.load(open('pbs.json'))
if 'assets' not in d:
    sys.exit('github api: %s' % d.get('message', d))
suffix='-$TRIPLE-install_only.tar.gz'
a=[x['browser_download_url'] for x in d['assets']
   if x['name'].startswith('cpython-$PYVER.') and x['name'].endswith(suffix)]
print(a[0] if a else '')")
  rm -f pbs.json
  [ -n "$URL" ] || { echo "no portable python $PYVER for $TRIPLE" >&2; exit 1; }
  mkdir runtime
  curl -sSL "$URL" -o runtime.tar.gz
  tar -x -z -f runtime.tar.gz -C runtime --strip-components=1
  rm runtime.tar.gz
fi

PY=runtime/bin/python3
[ -x "$PY" ] || PY=runtime/python.exe
"$PY" -m pip install --quiet -r app/requirements.txt -c constraints.txt

# TOPP tools are resolved via PATH by CommandExecutor; without them the Viewer and
# Upload pages work, the Workflow pages do not.
mkdir -p topp
if [ -n "$OPENMS_BIN" ]; then
  for t in FLASHDeconv FLASHTagger FLASHTnT FLASHQuant; do
    if [ -f "$OPENMS_BIN/$t" ]; then cp "$OPENMS_BIN/$t" topp/; else echo "note: $t not found in $OPENMS_BIN"; fi
  done
else
  echo "note: OPENMS_BIN unset, building without TOPP tools (Workflow pages will not run)"
fi

echo "ready: npm start"
