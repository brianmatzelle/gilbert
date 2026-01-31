import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), basicSsl()],
  server: {
    // HTTPS is provided by basicSsl plugin
    host: true,   // Listen on all interfaces (for Quest access via LAN IP)
    port: 5173,
    proxy: {
      // Proxy API calls to the Garvis server
      '/ws/voice': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ping': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/mcp': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Face detection endpoint for camera overlay
      '/detect-faces': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // Object detection endpoint (YOLO)
      '/detect': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
