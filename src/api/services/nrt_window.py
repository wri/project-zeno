"""The alert window of a near-real-time monitoring section.

Two numbers, in a module light enough for both the HTTP schema and the
recipe to import. ``nrt_monitoring`` pulls in the analytics handler, the
imagery provider and a model client; ``src.api.schemas`` is imported by
every request that authenticates, so it cannot pay for that just to state a
field default.
"""

#: Length of the alert window when the caller names none. Two weeks: these
#: sections are for what is happening now, and a reader changes the window
#: on demand when they want more history.
DEFAULT_DAYS = 14

#: The widest window the recipe will build. Alerts are near-real-time, so a
#: year is already well past what the section is for.
MAX_DAYS = 365
