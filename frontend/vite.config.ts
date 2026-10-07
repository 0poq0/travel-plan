import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 5173,
    // Windows 上编辑器保存文件时会先写 .tmpdir/*.tmp 再原子替换。Vite 的文件
    // 监视器会去 watch 这个瞬时临时目录, 而它随即被占用/删除, 于是抛
    // EBUSY: resource busy or locked 并让整个 dev server 崩溃退出(实测反复发生)。
    // 排除临时目录并改用轮询, 可避免这类崩溃。
    watch: {
      ignored: ['**/.tmpdir/**', '**/*.tmp', '**/node_modules/**', '**/dist/**'],
      usePolling: true,
      interval: 300
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})

