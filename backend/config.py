"""Every value the backend reads from the environment, in one place.

Two things this file exists to prevent.

The first is whitespace. A DATABASE_URL pasted into the Render dashboard with a
trailing newline took a deploy down: the newline travelled into the connection
string and the pool could not connect, with an error that pointed at the
database rather than at the paste. Dashboards, .env files and shell exports all
make that easy to do and none of them make it visible. So every variable is read
through get_env(), which strips it — the fix lives at the one point where values
enter the process rather than at each of the places they are used.

The second is a model id spelled out at more than one call site.
llama-3.3-70b-versatile was named twice, and when Groq decommissioned it both
call sites started failing at once. Because both of them catch exceptions and
fall back quietly, the endpoints kept returning 200 with the AI silently absent.
One value, overridable from the environment, means the next decommissioning is a
dashboard edit and not a deploy.
"""

import os
from typing import overload

from dotenv import load_dotenv

# Loaded here, not in main.py, so that anything importing config gets the .env
# values whether or not main has been imported first.
load_dotenv()

# Groq's free tier as of the llama-3.3-70b-versatile decommissioning. Override
# with GROQ_MODEL rather than editing this, so a model going away does not
# need a code change.
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"

# Nominatim's usage policy asks for a User-Agent that both names the application
# and gives them a way to reach whoever runs it; a bare product token is the
# shape their blocklists look for. The URL is the contact point. Overridable so
# that a fork, or a second deployment, can identify itself as itself rather than
# inheriting the blame — or the block — for this one.
DEFAULT_USER_AGENT = "DhakaRouteFinder/1.0 (github.com/riazur-13/dhaka-route-app)"


# The overloads are what let callers with a default treat the result as a plain
# str: without them every use site inherits an Optional it can never actually
# receive, and has to assert it away.
@overload
def get_env(name: str, default: str) -> str: ...


@overload
def get_env(name: str, default: None = None) -> str | None: ...


def get_env(name: str, default: str | None = None) -> str | None:
    """Return an environment variable stripped of surrounding whitespace.

    A variable that is unset and one holding nothing but whitespace are treated
    alike: both give the default. An all-whitespace value is never what anyone
    meant, and letting it through only moves the failure somewhere less obvious.
    """
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip() or default


GROQ_API_KEY = get_env("GROQ_API_KEY")
GROQ_MODEL = get_env("GROQ_MODEL", DEFAULT_GROQ_MODEL)
USER_AGENT = get_env("USER_AGENT", DEFAULT_USER_AGENT)
