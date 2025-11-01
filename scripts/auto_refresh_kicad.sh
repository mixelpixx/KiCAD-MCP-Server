#!/bin/bash
# Auto-refresh KiCAD when .kicad_pcb files change
# Usage: ./auto_refresh_kicad.sh /path/to/project.kicad_pcb

if [ -z "$1" ]; then
    echo "Usage: $0 <path-to-kicad-pcb-file>"
    exit 1
fi

PCB_FILE="$1"

if [ ! -f "$PCB_FILE" ]; then
    echo "Error: File not found: $PCB_FILE"
    exit 1
fi

echo "Monitoring: $PCB_FILE"
echo "When changes are saved, KiCAD will detect them and prompt to reload."
echo "Press Ctrl+C to stop monitoring."

# Watch for file changes
inotifywait -m -e modify "$PCB_FILE" |
while read path action file; do
    echo "[$(date '+%H:%M:%S')] File changed - KiCAD should prompt to reload"
    # KiCAD automatically detects file changes in most versions
done
