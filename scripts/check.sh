#!/usr/bin/env bash
# Verify command for this repo (Core role). Spends no credits: it only checks local files.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

echo "== Interface check on the sample files"
"$PY" -m core.interface core/fixtures/sample

echo "== Placeholder stems generate and still pass the interface check"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$PY" -m core.placeholders --out "$tmp/placeholder"
"$PY" -m core.interface "$tmp/placeholder"

echo "== Proof eval tests"
"$PY" -m unittest discover -s evals -t .

echo "== Surface mixer tests (timing and filter graph only, no ffmpeg needed)"
"$PY" -m unittest web.test_mix

echo "check.sh: all checks passed"
