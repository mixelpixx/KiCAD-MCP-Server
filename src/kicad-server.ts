/**
 * Backward-compatible executable alias.
 *
 * The canonical implementation lives in index.ts/server.ts. Keeping this
 * historical output path as a shim avoids publishing a second server with a
 * divergent tool catalogue, timeout queue, and protocol implementation.
 */
import "./index.js";
