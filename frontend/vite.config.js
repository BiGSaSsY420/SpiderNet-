import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false
      }
    }
  },
  test: {
    // 用例默认放在 tests/ 下；与组件同目录的 *.test.js 也会被拾取
    include: ['tests/**/*.test.js', 'src/**/*.test.js'],
    setupFiles: ['tests/setup.js'],
    coverage: {
      provider: 'v8',
      // 只统计有测试覆盖意义的逻辑代码：.vue 视图目前靠手工验收，
      // 计入会把数字稀释成噪声。详见 docs/TESTING.md。
      include: ['src/api/**/*.js', 'src/store/**/*.js', 'src/utils/**/*.js'],
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: 'coverage',
      // 防回退门槛，而非目标值；覆盖率提高后请同步上调。
      thresholds: {
        statements: 90,
        branches: 85,
        functions: 90,
        lines: 90
      }
    }
  }
})
