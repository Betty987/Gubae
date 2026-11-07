import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, eventCalendarUrl, type RSVPStatus } from '../api'
import { useAuth } from '../auth'
import { useLoad } from '../components/useLoad'
import { formatWhen } from '../format'

const RSVP_LABELS: Record<RSVPStatus, string> = { going: 'Going', maybe: 'Maybe', not_going: "Can't go" }

export default function EventPage() {
  const id = Number(useParams().id)
  const { user } = useAuth()
  const navigate = useNavigate()
  const { data: event, error, loading, reload } = useLoad(() => api.event(id), [id, user?.id])
  const [actionError, setActionError] = useState<string | null>(null)

  /** Run a mutation, then reload so counts/spots come fresh from the server.
   *  (The server is the source of truth: it knows about other people's RSVPs.) */
  async function act(fn: () => Promise<unknown>) {
    setActionError(null)
    try {
      await fn()
      await reload()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Something went wrong.')
    }
  }

  if (loading) return <p className="muted">Loading…</p>
  if (error || !event) return <p className="error">{error ?? 'Event not found.'}</p>

  const started = new Date(event.starts_at) <= new Date()

  return (
    <div className="detail">
      <Link to="/" className="muted small">← All events</Link>
      <p className="eyebrow">{event.community_name}</p>
      <h1>{event.title}</h1>
      <p className="muted">{formatWhen(event.starts_at, event.ends_at)}{event.location && ` · 📍 ${event.location}`}</p>
      {event.description && <p>{event.description}</p>}
      <a className="btn btn-outline small" href={eventCalendarUrl(event.id)}>📅 Add to my calendar</a>

      <section className="card">
        <div className="row">
          <h2>Are you coming?</h2>
          <span className="muted">
            {event.going_count} going
            {event.capacity !== null && ` · ${event.spots_left} of ${event.capacity} spots left`}
          </span>
        </div>
        {!user ? (
          <p className="muted"><Link to="/login">Log in</Link> to RSVP.</p>
        ) : started ? (
          <p className="muted">This event has already started.</p>
        ) : (
          <div className="btn-group">
            {(Object.keys(RSVP_LABELS) as RSVPStatus[]).map((s) => (
              <button
                key={s}
                className={`btn ${event.my_rsvp === s ? 'btn-primary' : 'btn-outline'}`}
                disabled={s === 'going' && event.spots_left === 0 && event.my_rsvp !== 'going'}
                onClick={() => act(() => api.rsvp(event.id, s))}
              >
                {RSVP_LABELS[s]}
              </button>
            ))}
            {event.my_rsvp && <button className="btn btn-ghost" onClick={() => act(() => api.cancelRsvp(event.id))}>Clear</button>}
          </div>
        )}
        {actionError && <p className="error">{actionError}</p>}
      </section>

      {(event.volunteer_slots.length > 0 || event.can_manage) && (
        <section className="card">
          <h2>Volunteer</h2>
          {event.volunteer_slots.length === 0 && <p className="muted">No volunteer slots yet.</p>}
          <ul className="slots">
            {event.volunteer_slots.map((slot) => {
              const full = slot.spots_filled >= slot.spots_needed
              return (
                <li key={slot.id}>
                  <div>
                    <strong>{slot.title}</strong>
                    <div className="progress"><div style={{ width: `${Math.min(100, (slot.spots_filled / slot.spots_needed) * 100)}%` }} /></div>
                    <span className="muted small">{slot.spots_filled} / {slot.spots_needed} filled</span>
                  </div>
                  {user && (slot.signed_up ? (
                    <button className="btn btn-ghost" onClick={() => act(() => api.unvolunteer(slot.id))}>Withdraw</button>
                  ) : (
                    <button className="btn btn-outline" disabled={full} onClick={() => act(() => api.volunteer(slot.id))}>
                      {full ? 'Filled' : 'I can help'}
                    </button>
                  ))}
                </li>
              )
            })}
          </ul>
          {event.can_manage && <AddSlotForm onAdd={(title, spots) => act(() => api.addSlot(event.id, title, spots))} />}
        </section>
      )}

      {event.can_manage && (
        <>
          <Attendees eventId={event.id} version={event.going_count} />
          <button
            className="btn btn-danger"
            onClick={() => {
              if (confirm(`Delete "${event.title}"? This also deletes all RSVPs.`)) {
                act(async () => { await api.deleteEvent(event.id); navigate('/') })
              }
            }}
          >
            Delete event
          </button>
        </>
      )}
    </div>
  )
}

function AddSlotForm({ onAdd }: { onAdd: (title: string, spots: number) => Promise<void> }) {
  const [title, setTitle] = useState('')
  const [spots, setSpots] = useState(1)
  async function submit(e: FormEvent) {
    e.preventDefault()
    await onAdd(title, spots)
    setTitle('')
    setSpots(1)
  }
  return (
    <form className="inline-form" onSubmit={submit}>
      <input placeholder="e.g. Bring injera" value={title} onChange={(e) => setTitle(e.target.value)} required />
      <input type="number" min={1} value={spots} onChange={(e) => setSpots(Number(e.target.value))} aria-label="Spots needed" />
      <button className="btn btn-outline">Add slot</button>
    </form>
  )
}

/** Admin-only guest list. `version` changes when RSVPs change, triggering a reload. */
function Attendees({ eventId, version }: { eventId: number; version: number }) {
  const { data } = useLoad(() => api.attendees(eventId), [eventId, version])
  return (
    <section className="card">
      <h2>Guest list <span className="muted small">(only admins see this)</span></h2>
      {data?.length === 0 && <p className="muted">No RSVPs yet.</p>}
      <ul className="guests">
        {data?.map((a) => (
          <li key={a.username}><span>{a.name}</span><span className={`chip ${a.status === 'going' ? 'chip-ok' : ''}`}>{RSVP_LABELS[a.status]}</span></li>
        ))}
      </ul>
    </section>
  )
}
