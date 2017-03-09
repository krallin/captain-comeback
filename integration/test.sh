#!/bin/bash
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

# This test ensures that the captain-comeback is able to keep the hog up for a
# while (despite the fact that the hog would otherwise die very quickly).
TEST_DURATION_S=60
RESTART_TIMEOUT_S=5
HOG_MEMORY_LIMIT=128mb

want_noswap
want_root
want_hog
clean_hog

# Check how long the hog takes to exhaust its limit
echo "Start hog: $(date)"
HOG_START_MS="$(date +%s%3N)"
run_hog_fg || true
HOG_END_MS="$(date +%s%3N)"
echo "Exit hog: $(date)"

# Start the captain
run_captain_bg --restart-grace-period "$RESTART_TIMEOUT_S" --wipe-fs

# Run the hog
echo "Start test: $(date)"
run_hog_bg
sleep "$TEST_DURATION_S"
echo "Exit test: $(date)"

terminate_captain

HOG_RUNTIME_MS="$((HOG_END_MS - HOG_START_MS))"
EXPECT_STARTS="$((TEST_DURATION_S * 1000 / (RESTART_TIMEOUT_S * 1000 + HOG_RUNTIME_MS)))"
ACTUAL_STARTS="$(hog_log | grep "hog up to" | wc -l)"

if [[ "$ACTUAL_STARTS" -lt "$EXPECT_STARTS" ]]; then
  echo "FAILED: ${ACTUAL_STARTS} / ${EXPECT_STARTS} restarts"
  hog_log
  RET=1
else
  echo "SUCCESS: ${ACTUAL_STARTS} / ${EXPECT_STARTS} restarts"
  RET=0
fi

clean_hog
exit "$RET"
