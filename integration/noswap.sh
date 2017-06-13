#!/bin/bash
set -o errexit
set -o nounset

swap_total="$(grep "SwapTotal" /proc/meminfo)"

if [[ ! "$swap_total" =~ SwapTotal:.+0\ kB ]]; then
  echo "You must disable swap to run tests"
  exit 1
fi
