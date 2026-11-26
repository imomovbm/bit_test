#!/usr/bin/env bash
# Linterlar (CI ham shuni ishlatadi): pyflakes (Python), ESLint (brauzer va E2E JS), node --check (sintaksis).
#   bash scripts/lint.sh
# ESLint: o'rnatilgan bo'lsa ESLINT=/yo'l/eslint, aks holda npx orqali qat'iy versiya (8.57.0 — eski CLI bayroqlari).
set -u
cd "$(dirname "$0")/.." || exit 1
ESLINT="${ESLINT:-npx --yes eslint@8.57.0}"
RULES='{"no-unused-vars":"error","no-undef":"error","no-unreachable":"error","no-dupe-keys":"error"}'
status=0
python3 -m pyflakes app tests scripts || status=1
$ESLINT --no-eslintrc --env browser,es2022 --parser-options=ecmaVersion:2022,sourceType:module --rule "$RULES" static/js/ || status=1
$ESLINT --no-eslintrc --env node,browser,es2022 --parser-options=ecmaVersion:2022 --rule "$RULES" e2e/ scripts/*.js || status=1
$ESLINT --no-eslintrc --env node,es2022 --parser-options=ecmaVersion:2022,sourceType:module --rule "$RULES" tests/js/ || status=1
for f in static/js/*.js static/js/views/*.js static/js/octagon/*.js; do
  node --input-type=module --check < "$f" || { echo "sintaksis: $f"; status=1; }
done
[ $status = 0 ] && echo "LINT OK"
exit $status
