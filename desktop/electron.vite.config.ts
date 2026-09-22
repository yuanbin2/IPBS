import { resolve } from 'path'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: {
        entry: resolve('electron/main.ts')
      }
    }
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      lib: {
        entry: resolve('electron/preload.ts')
      }
    }
  },
  renderer: {
    resolve: {
      alias: {
        '@': resolve('src')
      }
    },
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true
        }
      }
    },
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: {
          index: resolve('src/index.html')
        }
      }
    }
  }
})
