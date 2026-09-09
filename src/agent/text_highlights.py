"""The highlight-markup contract for the text blocks the app renders.

The app colours figures inside a text block. It finds them by a span with a
``data-highlight`` attribute, which the model writes into the text itself.
This module holds that contract once:

* ``HIGHLIGHT_GUIDE`` — the rules, for a text-generation system prompt.
* ``HIGHLIGHT_RULE`` — the same rules in one paragraph, for the tool
  fragments in the agent's system prompt, where space is short.
* ``strip_highlights`` — the markup removed again, for the places a text
  block is quoted back into the conversation instead of rendered.

Three kinds cover what a reader looks for: a figure, and a figure that went
up or down. The kinds state the direction of a change and never whether it
is good news — for tree cover loss an increase is bad news, and only the app
knows which palette a dataset uses.
"""

import re

HIGHLIGHT_KINDS = ("value", "increase", "decrease")

HIGHLIGHT_GUIDE = """# Highlighting figures

Mark up every figure in the body text with a highlight span. The app renders \
the span in a colour, so the reader finds the figures without reading the \
whole block:

- a figure: `As of 2020, <span data-highlight="value">27%</span> of the area \
was natural forest.`
- a figure that went up: `Alerts rose by <span \
data-highlight="increase">12%</span> against the year before.`
- a figure that went down: `Tree cover loss fell to <span \
data-highlight="decrease">4,200 ha</span>.`

Rules:

- Use `increase` or `decrease` only for a figure that states a change \
between two periods or two areas. Use `value` for every other figure, large \
or small.
- Wrap the figure with its unit, and with the word that carries the \
direction when the wording needs one ("up 12%", "a drop of 4,200 ha"). Wrap \
no more than that — never a whole sentence or clause.
- Write one span per figure, and never a span inside another span.
- Write no other HTML and no other attribute. No `class`, no `style`, no \
`<b>`, no `<div>`.
- Highlight the figures that answer the question. Dates, periods, area names \
and dataset names stay plain. Use `**bold**` for a name or a term you want \
to stress.
- The text must read correctly when the markup is removed.
- Highlight the body text only. A title, a heading, a chart label and a \
follow-up suggestion stay plain, and so does a reply you write in the chat.
"""

HIGHLIGHT_RULE = (
    "Highlight the figures: wrap each figure in the body text in a span the "
    'app colours — `<span data-highlight="value">27%</span>` for a figure, '
    '`data-highlight="increase"` or `"decrease"` for a figure that states a '
    'change ("rose by <span data-highlight="increase">12%</span>"). Wrap the '
    "figure and its unit only, never a whole sentence, and write no other "
    "HTML. Highlights belong in the text you pass to this tool — never in a "
    "heading and never in a reply you write in the chat."
)

_OPEN_SPAN = re.compile(r"<span[^>]*\bdata-highlight\b[^>]*>", re.IGNORECASE)
_CLOSE_SPAN = re.compile(r"</\s*span\s*>", re.IGNORECASE)


def strip_highlights(text: str) -> str:
    """The text with its highlight spans removed, keeping what they wrapped.

    Used where a text block is quoted back into the conversation — a tool
    message the chat shows, or a recalled summary the model rephrases —
    because only the app renders the markup. Stored text keeps it.
    """
    if "span" not in text.lower():
        return text
    return _CLOSE_SPAN.sub("", _OPEN_SPAN.sub("", text))
