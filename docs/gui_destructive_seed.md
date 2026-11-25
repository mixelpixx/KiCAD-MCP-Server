# GUI-driver destructive-label seed list

The seed list of destructive menu labels that `kicad_gui_tree` flags with
`destructive: true` and a `⚠ ` prefix lives in
[`python/resources/gui_destructive_seed.txt`](../python/resources/gui_destructive_seed.txt),
one label per line. It sits next to the code that reads it
(`python/commands/gui_driver.py`), so it ships with the Python code. The flag
is advisory only; nothing is gated on it.
