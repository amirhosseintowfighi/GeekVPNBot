import { defineConfig } from 'vitest/config'
import path from 'node:path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
  },
  resolve: {
    alias: {
      // Mirrors the `@/*` path mapping in tsconfig.json. Without this the
      // tests resolve imports differently from the build, which is exactly
      // the kind of drift that makes a green suite meaningless.
      '@': path.resolve(__dirname, './src'),
    },
  },
})
