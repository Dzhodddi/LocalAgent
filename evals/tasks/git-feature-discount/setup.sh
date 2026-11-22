set -euo pipefail
g() { git -c user.name=Setup -c user.email=setup@example.com "$@"; }
git init -q -b main
git init -q --bare -b main "$EVAL_REMOTE"
git remote add origin "$EVAL_REMOTE"
g add .
g commit -qm "Add orders"
g push -q origin main
