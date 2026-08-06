"""Ways find_duplicate_symbols can decide two symbols are the same part.

Dependency-free so the tool schema and the command share one list instead of
drifting apart.

``graphics`` is deliberately absent from the defaults: every resistor in a
library is drawn with the same body, so on passives it groups the whole family
and reports nothing useful. It earns its keep when hunting a custom part that
was copied under a new name.

``name`` is absent for the opposite reason -- it is the weakest signal, not the
loudest. It collapses the separators between the parts of a name, so ``R_10K``
and ``R-10K`` match, and finds little beyond a part re-added by retyping its
name. The decimal point is NOT collapsed: doing so makes ``C_1.0uF_0805`` and
``C_10uF_0805`` the same key.

Whatever the strategy, a key has to be a value and not a marker meaning the
field was left blank -- ``N/A``, ``TBD``, ``-``, KiCad's ``~``. Grouping on one
of those puts every part an importer could not fill in into a single group.
"""

DUPLICATE_STRATEGIES = ("mpn", "supplier", "value_footprint", "graphics", "name")

DEFAULT_DUPLICATE_STRATEGIES = ("mpn", "value_footprint")
