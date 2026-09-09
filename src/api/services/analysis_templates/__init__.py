"""Analysis templates: curated dashboard sections built in one call.

An analysis template answers a standing question about an area — "what has
been disturbed here in the last two weeks?" — by writing a whole dashboard
section at once: the chart, the map layers and the words that go with them.
It is not a chat workflow. Nothing is picked by a model along the way, so
the same request always produces the same section.

A section a template wrote is **sealed**: its content is a record of one
build, over one area and one period, so editing it would make its own title
untrue. Only the template that wrote it may replace its contents, and only
wholesale (a refresh onto a new period).

The parts:

* ``registry`` — the list of templates, as metadata only. Import-light, so
  the repository layer can read the seal list without pulling in an
  analytics client or a model.
* ``base`` — the interface a template implements, its result and error
  types, and the helpers every template shares.
* ``writer`` — the two transactional writes, and the one place the
  section's ``config`` shape is decided.
* one package per template, e.g. ``nrt_monitoring``.

To add a template, see ``docs/analysis-templates.md``.
"""
