import { BrowserRouter, Link, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import type { ReactNode } from 'react'
import { AuthProvider, useAuth } from './auth'
import EventsPage from './pages/EventsPage'
import EventPage from './pages/EventPage'
import CommunitiesPage from './pages/CommunitiesPage'
import NewEventPage from './pages/NewEventPage'
import { LoginPage, RegisterPage } from './pages/AuthPages'

/** Client-side routing: the URL decides which page component renders,
 *  without asking the server for a new HTML page. */
export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Header />
        <main className="container">
          <Routes>
            <Route path="/" element={<EventsPage />} />
            <Route path="/events/:id" element={<EventPage />} />
            <Route path="/communities" element={<CommunitiesPage />} />
            <Route path="/events/new" element={<RequireAuth><NewEventPage /></RequireAuth>} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="*" element={<p className="muted">Page not found.</p>} />
          </Routes>
        </main>
      </BrowserRouter>
    </AuthProvider>
  )
}

function Header() {
  const { user, logout } = useAuth()
  return (
    <header className="header">
      <div className="container header-inner">
        <Link to="/" className="brand">
          <span className="brand-mark">ጉ</span> Gubae
        </Link>
        <nav className="nav">
          <NavLink to="/" end>Events</NavLink>
          <NavLink to="/communities">Communities</NavLink>
          {user ? (
            <>
              <span className="muted hide-sm">Hi, {user.first_name || user.username}</span>
              <button className="btn btn-ghost" onClick={logout}>Log out</button>
            </>
          ) : (
            <>
              <NavLink to="/login">Log in</NavLink>
              <Link to="/register" className="btn btn-primary">Sign up</Link>
            </>
          )}
        </nav>
      </div>
    </header>
  )
}

/** Redirects to /login if nobody is logged in. This is a UX guard only:
 *  the REAL protection is the backend returning 401/403. Never trust the client. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return null
  return user ? children : <Navigate to="/login" replace />
}
