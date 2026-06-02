#!/bin/sh
python ls_json.py >package.json
python ../utils/gen_apps_db.py

#for f in *.py; do
#    base="${f%.py}"
#    "$MPY_CROSS" "$f" -o "mpy/${base}.mpy"
#done
