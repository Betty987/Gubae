import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, communityCalendarUrl, webcalUrl, type Community } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../components/useLoad'
import { slugify } from '../format'

export default function CommunitiesPage() {
  const { user } = useAuth()
  const { data, error, loading, reload } = useLoad(() => api.communities(), [user?.id])
  const [actionError, setActionError] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setActionError(null)
    try {
      await fn()
      await reload()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Something went wrong.')
    }
  }

  return (
    <>
      <section className="hero">
        <h1>Communities</h1>
        <p className="muted">Join your church, mahber or student association to RSVP and volunteer.</p>
      </section>
      {loading && <p className="muted">Loading…</p>}
      {(error || actionError) && <p className="error">{error || actionError}</p>}
      <div className="grid">
        {data?.map((c) => (
          <div key={c.slug} className="card community-card">
            <h3>{c.name}</h3>
            {c.description && <p className="muted small">{c.description}</p>}
            <p className="muted small">{c.member_count} member{c.member_count === 1 ? '' : 's'}</p>
            {user && c.my_role && (
              <label className="toggle small">
                <input type="checkbox" checked={c.notify_new_events ?? true}
                  onChange={(e) => act(() => api.setNotify(c.slug, e.target.checked))} />
                Email me about new events
              </label>
            )}
            <CalendarSubscribe community={c} />
            <div className="row">
              <Link to={`/?community=${c.slug}`} className="small">View events</Link>
              {!user ? null : c.my_role ? (
                <span className="row-gap">
                  <span className={`chip ${c.my_role === 'admin' ? 'chip-ok' : ''}`}>{c.my_role === 'admin' ? 'Admin' : 'Member'}</span>
                  <button className="btn btn-ghost" onClick={() => act(() => api.leave(c.slug))}>Leave</button>
                </span>
              ) : (
                <button className="btn btn-primary" onClick={() => act(() => api.join(c.slug))}>Join</button>
              )}
            </div>
          </div>
        ))}
      </div>
      {user && <CreateCommunity onCreated={reload} />}
    </>
  )
}

function CreateCommunity({ onCreated }: { onCreated: () => Promise<void> }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    try {
      await api.createCommunity({ name, slug: slugify(name), description })
      setName('')
      setDescription('')
      setOpen(false)
      await onCreated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create community.')
    }
  }

  if (!open) return <button className="btn btn-outline spaced" onClick={() => setOpen(true)}>+ Start a community</button>
  return (
    <form className="card form spaced" onSubmit={submit}>
      <h2>Start a community</h2>
      <p className="muted small">You'll be its first admin.</p>
      <label>Name<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
      <label>Description<textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} /></label>
      {error && <p className="error">{error}</p>}
      <div className="btn-group">
        <button className="btn btn-primary">Create</button>
        <button type="button" className="btn btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </form>
  )
}

/** One-time setup: the phone's calendar keeps pulling new events by itself. */
function CalendarSubscribe({ community }: { community: Community }) {
  const [copied, setCopied] = useState(false)
  const url = communityCalendarUrl(community.slug)
  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      window.prompt('Copy this calendar link:', url)
    }
  }
  return (
    <div className="calendar-row">
      <a className="btn btn-outline small" href={webcalUrl(url)}>📅 Subscribe in calendar</a>
      <button className="btn btn-ghost small" onClick={copy}>{copied ? 'Copied!' : 'Copy link'}</button>
    </div>
  )
}
