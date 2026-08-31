import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Vendored sherpa-onnx WASM glue (public/wasm/) and workers/*.ts's own
    // compiled output (public/workers/, see tsconfig.workers.json) -- not
    // hand-written project source, shouldn't be linted as such.
    "public/wasm/**",
    "public/workers/**",
    // Standalone native-build toolchain (Emscripten/CMake source, a plain
    // Node.js CLI test script) -- not part of the Next.js app, see its
    // own README.md.
    "native/**",
  ]),
]);

export default eslintConfig;
