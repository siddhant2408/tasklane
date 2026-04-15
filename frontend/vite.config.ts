import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
  ],
  server: {
    proxy: {
      '/tickets': 'http://localhost:8000',
      '/runs': 'http://localhost:8000',
      '/tools': 'http://localhost:8000',
      '/personas': 'http://localhost:8000',
      '/board': 'http://localhost:8000',
    },
  },
})
