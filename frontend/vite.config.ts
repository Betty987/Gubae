import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // DEV PROXY: the browser calls http://localhost:5173/api/..., and Vite
    // forwards it to Django on :8000. To the browser everything is the same
    // origin, so there are no CORS errors and no CORS config on the backend.
    // In production we'd do the same thing with nginx or by serving the
    // built React files from the same domain as the API.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
