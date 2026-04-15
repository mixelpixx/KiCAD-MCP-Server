import eslint from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.ts"],
    rules: {
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
      "@typescript-eslint/no-unsafe-function-type": "off",
      "preserve-caught-error": "off",
    },
  },
  {
    ignores: ["dist/", "node_modules/", "**/*.js", "!eslint.config.js"],
  },
);
