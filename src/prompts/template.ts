/**
 * Argument substitution for prompt templates.
 *
 * The prompt texts mark where each argument goes with {{name}}. The SDK passes
 * the arguments to the handler but does not fill them in, so a handler that
 * ignored its arguments sent the literal placeholder to the model and dropped
 * what the user supplied.
 */

import type { GetPromptResult } from "@modelcontextprotocol/sdk/types.js";

/** Text used for an optional argument the caller left out. */
export const NOT_PROVIDED = "(not provided)";

const PLACEHOLDER = /\{\{(\w+)\}\}/g;

/**
 * Replace each {{name}} in the result's text messages with args[name].
 *
 * Substitution is a single pass, so a value that itself contains {{...}} is
 * inserted as written and not expanded again. An optional argument the caller
 * left out (the SDK omits it from args) becomes NOT_PROVIDED.
 */
export function fillTemplate(
  args: Record<string, string | undefined>,
  result: GetPromptResult,
): GetPromptResult {
  return {
    ...result,
    messages: result.messages.map((message) =>
      message.content.type === "text"
        ? {
            ...message,
            content: {
              ...message.content,
              text: message.content.text.replace(PLACEHOLDER, (_match, name: string) => {
                const value = args[name];
                return value === undefined || value.trim() === "" ? NOT_PROVIDED : value;
              }),
            },
          }
        : message,
    ),
  };
}
