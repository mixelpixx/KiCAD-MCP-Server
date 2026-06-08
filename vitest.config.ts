import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests-ts/**/*.test.ts"],
    environment: "node",
    reporters: ["verbose"],
  },
});
