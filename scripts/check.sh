#!/usr/bin/env bash
# Verify command for this repo (Core role). Spends no credits: it only checks local files.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

echo "== Interface check on the sample files"
"$PY" -m core.interface core/fixtures/sample

echo "== Interface check on the real adaptation"
"$PY" -m core.interface core/adaptation/script.json

echo "== Placeholder stems generate and still pass the interface check"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$PY" -m core.placeholders --out "$tmp/placeholder"
"$PY" -m core.interface "$tmp/placeholder"

echo "== Core pipeline tests (fake ElevenLabs client: no credits, keys or network)"
"$PY" -m unittest discover -s core/tests -t .

echo "== Proof eval tests"
"$PY" -m unittest discover -s evals -t .

echo "== Surface mixer tests (timing and filter graph only, no ffmpeg needed)"
"$PY" -m unittest web.test_mix

echo "check.sh: all checks passed"
