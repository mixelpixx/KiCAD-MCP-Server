"""KiCad pin electrical types and graphic styles, as written in .kicad_sym.

Kept in a dependency-free module so both the tool schema and the command that
writes pins read the same list. KiCad refuses to load a library containing a
token outside these sets, and the error it reports names the file rather than
the pin, so the check has to happen before the write.
"""

PIN_TYPES = (
    "input",
    "output",
    "bidirectional",
    "tri_state",
    "passive",
    "free",
    "unspecified",
    "power_in",
    "power_out",
    "open_collector",
    "open_emitter",
    "no_connect",
)

PIN_STYLES = (
    "line",
    "inverted",
    "clock",
    "inverted_clock",
    "input_low",
    "clock_low",
    "output_low",
    "edge_clock_high",
    "non_logic",
)
