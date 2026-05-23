export type McpTextResult = {
  content: Array<{
    type: "text";
    text: string;
  }>;
  isError?: true;
};

function isKicadFailure(result: unknown): boolean {
  return (
    typeof result === "object" &&
    result !== null &&
    "success" in result &&
    (result as { success?: unknown }).success === false
  );
}

export function formatKicadResult(result: unknown): McpTextResult {
  const text = JSON.stringify(result) ?? String(result);

  return {
    content: [
      {
        type: "text",
        text,
      },
    ],
    ...(isKicadFailure(result) ? { isError: true as const } : {}),
  };
}
