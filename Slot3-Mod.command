#!/bin/zsh
set -u
cd "${0:A:h}"
python3 tools/slot3_mod.py "$@"
result=$?
if [[ $# == 0 && -t 0 ]]; then
  printf '\nPress Return to close. '
  read -r answer
fi
exit "$result"
