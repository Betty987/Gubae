import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Event } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../components/useLoad'
import { dateBadge, formatWhen } from '../format'

export default function EventsPage() {
  const { user } = useAuth()
  // The community filter lives in the URL (?community=st-mary...), so links
  // and the back button work, and a filtered view can be shared.
  const [params, setParams] = useSearchParams()
  const community = params.get('community') ?? ''
  const setCommunity = (slug: string) => setParams(slug ? { community: slug } : {})
  const [upcoming, setUpcoming] = useState(true)

  // Re-runs whenever a filter changes OR the user logs in/out
  // (my_rsvp / can_manage depend on who's asking).
  const events = useLoad(() => api.events({ community, upcoming }), [community, upcoming, user?.id])
  const communities = useLoad(() => api.communities(), [user?.id])
  const adminOf = (communities.data ?? []).filter((c) => c.my_role === 'admin')

  return (
    <>
      <section className="hero">
        <h1>What's happening in your community</h1>
        <p className="muted">Church services, holidays, fellowship and volunteering, all in one place instead of buried in group chats.</p>
      </section>

      <div className="toolbar">
        <select value={community} onChange={(e) => setCommunity(e.target.value)} aria-label="Filter by community">
          <option value="">All communities</option>
          {communities.data?.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
        </select>
        <label className="toggle">
          <input type="checkbox" checked={upcoming} onChange={(e) => setUpcoming(e.target.checked)} />
          Upcoming only
        </label>
        {adminOf.length > 0 && <Link to="/events/new" className="btn btn-primary push-right">+ New event</Link>}
      </div>

      {events.loading && <p className="muted">Loading events…</p>}
      {events.error && <p className="error">{events.error}</p>}
      {events.data?.length === 0 && <p className="muted empty">No events yet.</p>}
      <div className="grid">
        {events.data?.map((e) => <EventCard key={e.id} event={e} />)}
      </div>
    </>
  )
}

function EventCard({ event }: { event: Event }) {
  const badge = dateBadge(event.starts_at)
  return (
    <Link to={`/events/${event.id}`} className="card event-card">
      <div className="date-badge"><span>{badge.month}</span><strong>{badge.day}</strong></div>
      <div className="event-body">
        <p className="eyebrow">{event.community_name}</p>
        <h3>{event.title}</h3>
        <p className="muted small">{formatWhen(event.starts_at, event.ends_at)}</p>
        {event.location && <p className="muted small">📍 {event.location}</p>}
        <div className="chips">
          <span className="chip">{event.going_count} going</span>
          {event.spots_left !== null && (
            <span className={`chip ${event.spots_left === 0 ? 'chip-warn' : ''}`}>
              {event.spots_left === 0 ? 'Full' : `${event.spots_left} spots left`}
            </span>
          )}
          {event.my_rsvp === 'going' && <span className="chip chip-ok">You're going</span>}
          {event.volunteer_slots.length > 0 && <span className="chip">🙋 Volunteers needed</span>}
        </div>
      </div>
    </Link>
  )
}
