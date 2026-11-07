/**
 * Auth state shared by the whole app (React Context).
 *
 * Without context, every component that needs "who is logged in?" would have
 * to receive it as a prop through every parent. Context makes it available
 * anywhere via useAuth().
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, tokens, type User } from './api'

interface AuthState {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  // Only "loading" if there's a saved token to check.
  const [loading, setLoading] = useState(() => tokens.access !== null)

  // On page load: if we have a saved token, ask the server who we are.
  // If the token is dead, api.me() fails and we stay logged out.
  useEffect(() => {
    if (!tokens.access) return
    api.me()
      .then(setUser)
      .catch(() => tokens.clear())
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    await api.login(username, password)
    setUser(await api.me())
  }, [])

  const logout = useCallback(() => {
    // JWTs are stateless: "logging out" = the client forgets the token.
    // (Production upgrade: blacklist the refresh token on the server too.)
    tokens.clear()
    setUser(null)
  }, [])

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
