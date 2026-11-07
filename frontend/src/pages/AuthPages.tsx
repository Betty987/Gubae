import { useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault() // stop the browser's default full-page form submit
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card form narrow" onSubmit={onSubmit}>
      <h1>Welcome back</h1>
      <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label>
      <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
      {error && <p className="error">{error}</p>}
      <button className="btn btn-primary" disabled={busy}>{busy ? 'Logging in…' : 'Log in'}</button>
      <p className="muted small">Demo: <code>demo_admin</code> / <code>gubae-demo-2026</code></p>
      <p className="muted small">New here? <Link to="/register">Create an account</Link></p>
    </form>
  )
}

export function RegisterPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ first_name: '', username: '', email: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (field: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [field]: e.target.value })

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.register(form)
      await login(form.username, form.password) // log straight in after signing up
      navigate('/communities')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign up failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card form narrow" onSubmit={onSubmit}>
      <h1>Join Gubae</h1>
      <label>First name<input value={form.first_name} onChange={set('first_name')} /></label>
      <label>Username<input value={form.username} onChange={set('username')} autoComplete="username" required /></label>
      <label>Email<input type="email" value={form.email} onChange={set('email')} autoComplete="email" required /></label>
      <label>Password<input type="password" value={form.password} onChange={set('password')} autoComplete="new-password" required minLength={8} /></label>
      {error && <p className="error">{error}</p>}
      <button className="btn btn-primary" disabled={busy}>{busy ? 'Creating account…' : 'Sign up'}</button>
      <p className="muted small">Already have an account? <Link to="/login">Log in</Link></p>
    </form>
  )
}
