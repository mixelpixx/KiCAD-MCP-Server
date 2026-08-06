"""Ways find_duplicate_symbols can decide two symbols are the same part.

Dependency-free so the tool schema and the command share one list instead of
drifting apart.

``graphics`` is deliberately absent from the defaults: every resistor in a
library is drawn with the same body, so on passives it groups the whole family
and reports nothing useful. It earns its keep when hunting a custom part that
was copied under a new name.
"""

DUPLICATE_STRATEGIES = ("mpn", "supplier", "value_footprint", "graphics", "name")

DEFAULT_DUPLICATE_STRATEGIES = ("mpn", "value_footprint")
