"""Hermetic backend fixture for MCP transport and project-handle CI tests."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _response(command: str, params: Dict[str, Any], board_path: Optional[str]) -> Dict[str, Any]:
    if command == "_warmup":
        return {"success": True, "version": "protocol-fixture", "elapsed_s": 0}
    if command == "create_project":
        path = Path(str(params["path"])) / f"{params['name']}.kicad_pcb"
        return {"success": True, "boardPath": path.as_posix()}
    if command == "get_project_info":
        return {"success": True, "boardPath": board_path}
    if command == "close_project":
        return {"success": True, "message": "Project closed"}
    return {"success": False, "message": f"Unsupported fixture command: {command}"}


def main() -> None:
    board_path: Optional[str] = None
    print(json.dumps({"type": "ready"}), flush=True)

    for raw_line in sys.stdin:
        request = json.loads(raw_line)
        command = str(request.get("command", ""))
        params = request.get("params") or {}
        result = _response(command, params, board_path)
        if command == "create_project" and result.get("success"):
            board_path = str(result["boardPath"])
        elif command == "close_project" and result.get("success"):
            board_path = None
        result["_requestId"] = request.get("requestId")
        print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
