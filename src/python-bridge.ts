import { randomUUID } from "node:crypto";

export interface PythonBridgeLogger {
  debug(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

export interface PythonCommandRequest {
  requestId: string;
  command: string;
  params: unknown;
}

export interface PythonCommandBridgeOptions {
  writeRequest(request: PythonCommandRequest): void;
  logger: PythonBridgeLogger;
  onDrainTimeout(request: PythonCommandRequest): void;
  drainGraceMs?: number;
  maxQueueSize?: number;
}

interface PendingRequest {
  request: PythonCommandRequest;
  timeoutMs: number;
  signal?: AbortSignal;
  abortListener?: () => void;
  timeoutHandle?: NodeJS.Timeout;
  settled: boolean;
  resolve(value: unknown): void;
  reject(reason: Error): void;
}

function abortError(command: string): Error {
  const error = new Error(`KiCad command cancelled: ${command}`);
  error.name = "AbortError";
  return error;
}

function asError(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(String(reason));
}

/**
 * Serializes commands to the synchronous Python stdin loop and correlates every
 * response with the request that produced it.
 *
 * A timed-out/cancelled command may still finish in Python. Its request ID is
 * retained in `expiredRequestIds`, so that late response is discarded instead
 * of being delivered to the next queued command.
 */
export class PythonCommandBridge {
  private static readonly MAX_EXPIRED_REQUEST_IDS = 1_024;
  private readonly writeRequest: (request: PythonCommandRequest) => void;
  private readonly logger: PythonBridgeLogger;
  private readonly onDrainTimeout: (request: PythonCommandRequest) => void;
  private readonly drainGraceMs: number;
  private readonly maxQueueSize: number;
  private readonly queue: PendingRequest[] = [];
  private readonly expiredRequestIds = new Set<string>();
  private active: PendingRequest | null = null;
  /**
   * A timed-out/cancelled command remains physically active in the synchronous
   * Python worker until its response arrives. Keep later requests out of stdin
   * until that response drains, otherwise their timers can expire before they
   * even begin and stale mutations will execute without a live caller.
   */
  private drainingRequestId: string | null = null;
  /** Once termination is requested, no response may resume this worker. */
  private drainEscalated = false;
  private drainTimeoutHandle?: NodeJS.Timeout;
  private responseBuffer = "";
  private closedError: Error | null = null;

  constructor(options: PythonCommandBridgeOptions) {
    this.writeRequest = options.writeRequest;
    this.logger = options.logger;
    this.onDrainTimeout = options.onDrainTimeout;
    this.drainGraceMs = options.drainGraceMs ?? 5_000;
    this.maxQueueSize = options.maxQueueSize ?? 128;
  }

  get queueDepth(): number {
    return this.queue.length + (this.active ? 1 : 0) + (this.drainingRequestId ? 1 : 0);
  }

  execute(
    command: string,
    params: unknown,
    timeoutMs: number,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (this.closedError) {
      return Promise.reject(this.closedError);
    }
    if (signal?.aborted) {
      return Promise.reject(abortError(command));
    }
    if (this.queueDepth >= this.maxQueueSize) {
      return Promise.reject(
        new Error(`KiCad command queue is full (${this.maxQueueSize} requests)`),
      );
    }

    return new Promise((resolve, reject) => {
      const pending: PendingRequest = {
        request: {
          requestId: randomUUID(),
          command,
          params,
        },
        timeoutMs,
        signal,
        settled: false,
        resolve,
        reject,
      };

      if (signal) {
        pending.abortListener = () => this.cancel(pending);
        signal.addEventListener("abort", pending.abortListener, { once: true });
      }

      this.queue.push(pending);
      this.processNext();
    });
  }

  /** Accept stdout chunks from the Python worker. */
  handleChunk(data: Buffer | string): void {
    this.responseBuffer += data.toString();

    let newlineIndex = this.responseBuffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = this.responseBuffer.slice(0, newlineIndex).trim();
      this.responseBuffer = this.responseBuffer.slice(newlineIndex + 1);
      if (line) {
        this.handleLine(line);
      }
      newlineIndex = this.responseBuffer.indexOf("\n");
    }
  }

  /** Reject active and queued requests when the worker exits or the server stops. */
  failAll(reason: unknown): void {
    const error = asError(reason);
    const active = this.active;
    this.active = null;
    if (active) {
      this.cleanup(active);
      this.rejectOnce(active, error);
    }

    for (const pending of this.queue.splice(0)) {
      this.cleanup(pending);
      this.rejectOnce(pending, error);
    }
    this.drainingRequestId = null;
    this.drainEscalated = false;
    if (this.drainTimeoutHandle) {
      clearTimeout(this.drainTimeoutHandle);
      this.drainTimeoutHandle = undefined;
    }
    this.expiredRequestIds.clear();
    this.responseBuffer = "";
  }

  close(reason: unknown = new Error("KiCad command bridge closed")): void {
    this.closedError = asError(reason);
    this.failAll(this.closedError);
  }

  private handleLine(line: string): void {
    let result: Record<string, unknown>;
    try {
      const parsed = JSON.parse(line) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        this.logger.warn(`Ignoring non-object Python response: ${line.slice(0, 160)}`);
        return;
      }
      result = parsed as Record<string, unknown>;
    } catch {
      this.logger.warn(`Ignoring non-JSON Python stdout: ${line.slice(0, 160)}`);
      return;
    }

    const requestId = result.requestId;
    if (typeof requestId !== "string" || requestId.length === 0) {
      this.logger.warn("Ignoring Python response without requestId");
      return;
    }

    if (this.expiredRequestIds.delete(requestId)) {
      this.logger.warn(`Discarded late Python response for expired request ${requestId}`);
      if (this.drainingRequestId === requestId) {
        this.drainingRequestId = null;
        if (this.drainTimeoutHandle) {
          clearTimeout(this.drainTimeoutHandle);
          this.drainTimeoutHandle = undefined;
        }
        if (!this.drainEscalated) this.processNext();
      }
      return;
    }

    if (!this.active) {
      this.logger.warn(`Ignoring Python response ${requestId} with no active request`);
      return;
    }

    if (this.active.request.requestId !== requestId) {
      this.logger.warn(
        `Ignoring out-of-order Python response ${requestId}; waiting for ${this.active.request.requestId}`,
      );
      return;
    }

    const pending = this.active;
    this.active = null;
    this.cleanup(pending);

    const publicResult = { ...result };
    delete publicResult.requestId;
    this.resolveOnce(pending, publicResult);
    this.processNext();
  }

  private processNext(): void {
    if (this.active || this.drainingRequestId || this.drainEscalated || this.closedError) {
      return;
    }

    const pending = this.queue.shift();
    if (!pending) {
      return;
    }

    if (pending.signal?.aborted) {
      this.cleanup(pending);
      this.rejectOnce(pending, abortError(pending.request.command));
      this.processNext();
      return;
    }

    this.active = pending;
    pending.timeoutHandle = setTimeout(() => this.timeout(pending), pending.timeoutMs);

    try {
      this.logger.debug(
        `Sending KiCad command ${pending.request.command} (${pending.request.requestId})`,
      );
      this.writeRequest(pending.request);
    } catch (reason) {
      this.active = null;
      this.cleanup(pending);
      this.rejectOnce(pending, asError(reason));
      this.processNext();
    }
  }

  private timeout(pending: PendingRequest): void {
    if (this.active !== pending || pending.settled) {
      return;
    }

    this.active = null;
    this.beginDrain(pending);
    this.cleanup(pending);
    this.rejectOnce(
      pending,
      new Error(
        `KiCad command timed out after ${pending.timeoutMs / 1000}s: ${pending.request.command}`,
      ),
    );
  }

  private cancel(pending: PendingRequest): void {
    if (pending.settled) {
      return;
    }

    if (this.active === pending) {
      this.active = null;
      this.beginDrain(pending);
      this.cleanup(pending);
      this.rejectOnce(pending, abortError(pending.request.command));
      return;
    }

    const index = this.queue.indexOf(pending);
    if (index >= 0) {
      this.queue.splice(index, 1);
      this.cleanup(pending);
      this.rejectOnce(pending, abortError(pending.request.command));
    }
  }

  private cleanup(pending: PendingRequest): void {
    if (pending.timeoutHandle) {
      clearTimeout(pending.timeoutHandle);
      pending.timeoutHandle = undefined;
    }
    if (pending.signal && pending.abortListener) {
      pending.signal.removeEventListener("abort", pending.abortListener);
      pending.abortListener = undefined;
    }
  }

  private markExpired(requestId: string): void {
    this.expiredRequestIds.add(requestId);
    while (this.expiredRequestIds.size > PythonCommandBridge.MAX_EXPIRED_REQUEST_IDS) {
      const oldest = this.expiredRequestIds.values().next().value as string | undefined;
      if (!oldest) break;
      this.expiredRequestIds.delete(oldest);
    }
  }

  private beginDrain(pending: PendingRequest): void {
    const requestId = pending.request.requestId;
    this.markExpired(requestId);
    this.drainingRequestId = requestId;
    this.drainEscalated = false;
    if (this.drainTimeoutHandle) clearTimeout(this.drainTimeoutHandle);
    this.drainTimeoutHandle = setTimeout(() => {
      this.drainTimeoutHandle = undefined;
      if (this.drainingRequestId !== requestId) return;
      this.drainEscalated = true;
      this.logger.error(
        `Python command ${pending.request.command} (${requestId}) did not drain after ${this.drainGraceMs}ms; restarting the worker`,
      );
      try {
        this.onDrainTimeout(pending.request);
      } catch (reason) {
        this.logger.error(
          `Could not restart the undrained Python worker: ${asError(reason).message}`,
        );
      }
    }, this.drainGraceMs);
    this.drainTimeoutHandle.unref?.();
  }

  private resolveOnce(pending: PendingRequest, value: unknown): void {
    if (pending.settled) return;
    pending.settled = true;
    pending.resolve(value);
  }

  private rejectOnce(pending: PendingRequest, reason: Error): void {
    if (pending.settled) return;
    pending.settled = true;
    pending.reject(reason);
  }
}
