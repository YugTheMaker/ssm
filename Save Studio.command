#!/bin/zsh
exec python3 "${0:A:h}/tools/ss_web.py" --open "$@"
