import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Shape taken from the Vitest guide bundled with this Next version, at
// node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md — with one
// deliberate departure. That guide installs vite-tsconfig-paths, and this Vite
// version prints a deprecation notice saying paths resolution is now native via
// resolve.tsconfigPaths. Heeding the notice rather than the guide, since the
// notice is the one that knows which Vite is actually installed.
export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./vitest.setup.ts'],
    // Only our own tests. Without this Vitest walks node_modules and tries to
    // run every package's own suite.
    include: ['app/**/*.test.{ts,tsx}'],
  },
});
