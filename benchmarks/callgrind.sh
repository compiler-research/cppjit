#!/usr/bin/env bash
# Count the instructions of every benchmark in test_calls.py under callgrind
# and write them to a JSON file for report.py.
#
#   ./callgrind.sh OUT.json [report.py collect options] [-- pytest args]
#
# Needs valgrind on PATH and setarch; CPPFLAGS (for make) may point at the
# valgrind headers. PYTHON picks the interpreter (default: python on PATH).
# In docker, ASLR can only be turned off with
# --security-opt seccomp=unconfined.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
out="$(realpath -m "$1")"
shift
collect_args=()
while [[ $# -gt 0 && "$1" != "--" ]]; do
  collect_args+=("$1")
  shift
done
[[ $# -gt 0 ]] && shift
python="$(command -v "${PYTHON:-python}")"

dumps="$(mktemp -d)"
trap 'rm -rf "${dumps}"' EXIT

cd "${here}"
# always: make cannot tell that a library built without CPPFLAGS (say, by a
# plain pytest run) lacks the markers
make -B cpp/callsDict.so
# Counts depend on memory layout (hash tables keyed by address), so run with
# ASLR off and a fixed environment: its size moves the stack. A fixed hash
# seed keeps dict and set layouts the same too.
valgrind="$(command -v valgrind)"
run_env=(
  PATH=/usr/local/bin:/usr/bin:/bin
  HOME=/tmp
  PYTHONHASHSEED=0
  CPPJIT_BENCH_CALLGRIND=1
)
if [[ -n "${CPPINTEROP_EXTRA_INTERPRETER_ARGS:-}" ]]; then
  run_env+=(CPPINTEROP_EXTRA_INTERPRETER_ARGS="${CPPINTEROP_EXTRA_INTERPRETER_ARGS}")
fi
env -i "${run_env[@]}" setarch -R "${valgrind}" -q --tool=callgrind \
  --collect-atstart=no \
  --callgrind-out-file="${dumps}/callgrind.out" \
  "${python}" -m pytest test_calls.py -p no:cacheprovider -q "$@"
"${python}" report.py collect "${dumps}" -o "${out}" \
  ${collect_args[@]+"${collect_args[@]}"}
