#!/usr/bin/env bash
# Run every test. Exits non-zero if any fail.
#
#   tests/run_all.sh
#
# The end-to-end test needs a FLASHDeconv binary (OPENMS_BIN, desktop/topp/, or
# PATH) and the pipeline test needs example-data/; both skip cleanly without
# them rather than reporting a false pass.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-desktop/runtime/bin/python3}
[ -x "$PY" ] || PY=python3

# pyopenms picks up a developer shell's OPENMS_DATA_PATH and warns; unset it so
# the bundled share directory is used.
export -n OPENMS_DATA_PATH 2>/dev/null || true
unset OPENMS_DATA_PATH

fail=0
run() {
  echo "=== $1"
  if FLASHAPP_DESKTOP=${2:-0} "$PY" "$1" 2>&1 \
      | grep -vE "WARNING|Determination of memory|measuring for memoryleaks|ScriptRunContext|MemoryCacheStorageManager"; then :; fi
  # shellcheck disable=SC2181
  if [ "${PIPESTATUS[0]}" -ne 0 ]; then fail=1; echo "  -> FAILED"; fi
  echo
}

run src/presets.py
run tests/test_presets.py
run tests/test_hosted_mode.py
run tests/test_workspace_name.py
run tests/test_filemanager_sql.py
run tests/test_linked_files.py 1
run tests/test_dialogs_and_workspace.py
run tests/test_intent.py
run tests/test_tool_roles.py
run tests/test_input_listing.py
run tests/test_partial_upload.py
run tests/test_example_data.py
run tests/test_workflow_pipeline.py
run tests/test_end_to_end.py

if [ "$fail" -ne 0 ]; then echo "SUITE FAILED"; exit 1; fi
echo "SUITE PASSED"
