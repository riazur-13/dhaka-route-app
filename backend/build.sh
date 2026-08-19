#!/usr/bin/env bash
#
# Build command for the Render backend service.
#
# Set the service's Build Command to one of:
#   bash backend/build.sh     — if Root Directory is blank (repo root)
#   bash build.sh             — if Root Directory is set to "backend"
#
# Why the import check exists: commit a2e92f6 shipped a one-character
# indentation slip that left main.py unparseable. The build still reported
# success, because Render never executes the app at build time — the failure
# only appeared when the service tried to start, and the API stayed down for
# days. Importing the module here turns that class of mistake into a failed
# build instead of a silent outage.

set -euo pipefail

cd "$(dirname "$0")"

pip install -r requirements.txt

echo "Verifying main.py imports cleanly..."

# A placeholder key keeps this independent of secrets. The Groq client refuses
# to construct without an api_key, and module import is what we are checking
# here — not credentials, and not any network call.
#
# No DATABASE_URL is needed either: the Postgres pool is built on first query,
# not at import, precisely so this check stays offline.
GROQ_API_KEY="${GROQ_API_KEY:-build-check-placeholder}" python -c "
import main

assert main.app.routes, 'FastAPI app registered no routes'
print(f'OK: main.py imported, {len(main.app.routes)} routes registered')
"
