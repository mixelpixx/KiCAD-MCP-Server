/**
 * Resource helper utilities for MCP resources
 */

/**
 * Create a JSON response for MCP resources
 *
 * @param data Data to serialize as JSON
 * @param uri Optional URI for the resource
 * @returns MCP resource response object
 */
export function createJsonResponse(data: any, uri?: string) {
  return {
    contents: [{
      uri: uri || "data:application/json",
      mimeType: "application/json",
      text: JSON.stringify(data, null, 2)
    }]
  };
}

/**
 * Create a binary response for MCP resources
 *
 * @param data Binary data (Buffer or base64 string)
 * @param mimeType MIME type of the binary data
 * @param uri Optional URI for the resource
 * @returns MCP resource response object
 */
export function createBinaryResponse(data: Buffer | string, mimeType: string, uri?: string) {
  const blob = typeof data === 'string' ? data : data.toString('base64');

  return {
    contents: [{
      uri: uri || `data:${mimeType}`,
      mimeType: mimeType,
      blob: blob
    }]
  };
}

/**
 * Create an error response for MCP resources
 *
 * @param error Error message
 * @param details Optional error details
 * @param uri Optional URI for the resource
 * @returns MCP resource error response
 */
export function createErrorResponse(error: string, details?: string, uri?: string) {
  return {
    contents: [{
      uri: uri || "data:application/json",
      mimeType: "application/json",
      text: JSON.stringify({
        error,
        details
      }, null, 2)
    }]
  };
}
