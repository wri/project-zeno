"""Authorization scopes for machine API keys.

A scope is a fine-grained permission carried by an individual machine key (see
``MachineUserKeyOrm.scopes``). Endpoints gate on a scope via ``require_scope`` so
machine-to-machine access is decoupled from ``user_type`` (a superuser human
always passes; a machine key passes iff it carries the scope).
"""

# Read access to the ingested Langfuse traces API (/api/traces/*).
TRACES_READ = "traces:read"

# All scopes the CLI is allowed to mint.
KNOWN_SCOPES = frozenset({TRACES_READ})
