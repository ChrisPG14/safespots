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
    ".test-output/**",
    "next-env.d.ts",
    // Código de terceros: el worker de MapLibre viene minificado y lo copia
    // scripts/copiar-worker-maplibre.mjs desde node_modules. Sin esta
    // exclusión aporta más de mil avisos que ahogan los de nuestro código.
    "public/maplibre/**",
  ]),
]);

export default eslintConfig;
