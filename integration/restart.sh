#!/bin/bash
set -o errexit
set -o nounset

REL_HERE=$(dirname "${BASH_SOURCE}")
HERE=$(cd "${REL_HERE}"; pwd)
cd "$HERE"
. lib.sh

# This test ensures that the captain-comeback is able to smoothly restart the hog.
HOG_MEMORY_LIMIT="$((1024 * 1024 * 128))"
HOG_ALLOC_LIMIT="$HOG_MEMORY_LIMIT"

want_noswap
want_root
want_hog
clean_hog

run_captain_bg
run_hog_bg

sleep 15
terminate_captain

HOG_STARTS="$(hog_log | grep "hog up to" | wc -l)"
HOG_EXITS="$(hog_log | grep "exit: SIGTERM" | wc -l)"

if [[ "$HOG_STARTS" -lt 2 ]]; then
  echo "FAIL: Hog was not restarted"
  hog_log
  exit 1
fi

if [[ "$HOG_EXITS" -lt 1 ]]; then
  echo "FAIL: Hog did not exit cleanly"
  hog_log
  exit 1
fi

echo "SUCCESS"
exit 0
