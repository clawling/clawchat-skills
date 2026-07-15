import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import("svelte/compiler").CompileOptions} */
const config = {
  preprocess: vitePreprocess(),
  compilerOptions: {
    // Svelte's default scoped-CSS hash includes the absolute filename. Hash
    // CSS bytes instead so committed output is reproducible across checkouts.
    cssHash: ({ css, hash }) => `svelte-${hash(css)}`,
  },
};

export default config;
