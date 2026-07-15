import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  base: "/",
  plugins: [tailwindcss(), svelte()],
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL("./src/lib", import.meta.url)),
    },
  },
  build: {
    assetsDir: "assets",
    emptyOutDir: true,
    outDir: "../dist",
    sourcemap: false,
    target: "es2022",
  },
});
