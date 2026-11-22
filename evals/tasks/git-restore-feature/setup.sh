set -euo pipefail
g() { git -c user.name=Setup -c user.email=setup@example.com "$@"; }
git init -q -b main
git init -q --bare -b main "$EVAL_REMOTE"
git remote add origin "$EVAL_REMOTE"
g add .
g commit -qm "Add calculator"
g push -q origin main
# Broken work in progress, never committed.
cat > calc.py <<'PY'
def add(a, b):
    return a - b  # WIP: experimenting


def multiply(a, b):
    return a * b * 2  # WIP
PY
