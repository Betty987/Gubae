import { useState, type ChangeEvent, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type EventDraft } from '../api'
import { useLoad } from '../components/useLoad'
import { toLocalInput } from '../format'

interface Slot { title: string; spots_needed: number }

const EXAMPLE = `Selam everyone! 🙏 Timket celebration is on Jan 19 at 10am at the church hall. Please wear white. We need 6 people to bring injera and 4 to help set up chairs. Kids' program after the service!`

export default function NewEventPage() {
  const navigate = useNavigate()
  const communities = useLoad(() => api.communities(), [])
  const adminOf = (communities.data ?? []).filter((c) => c.my_role === 'admin')

  // Lazy initial state: the function runs once, not on every render.
  const [form, setForm] = useState(() => {
    const tomorrow = new Date(Date.now() + 24 * 3600 * 1000)
    tomorrow.setHours(18, 0, 0, 0)
    return {
      community: '',
      title: '',
      description: '',
      location: '',
      starts_at: toLocalInput(tomorrow),
      ends_at: toLocalInput(new Date(tomorrow.getTime() + 2 * 3600 * 1000)),
      capacity: '',
    }
  })
  const [slots, setSlots] = useState<Slot[]>([])
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const set = (field: keyof typeof form) =>
    (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
      setForm({ ...form, [field]: e.target.value })

  const community = form.community || adminOf[0]?.slug || ''

  /** AI result -> pre-fill the form. The admin still reviews and saves. */
  function applyDraft(d: EventDraft) {
    setForm((f) => ({
      ...f,
      title: d.title || f.title,
      description: d.description || f.description,
      location: d.location || f.location,
      starts_at: d.starts_at ? toLocalInput(new Date(d.starts_at)) : f.starts_at,
      ends_at: d.ends_at ? toLocalInput(new Date(d.ends_at)) : f.ends_at,
      capacity: d.capacity ? String(d.capacity) : f.capacity,
    }))
    setSlots(d.volunteer_slots)
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      const event = await api.createEvent({
        ...form,
        community,
        // The input gives local time with no zone; new Date() reads it as local,
        // toISOString() converts to UTC. The server stores UTC.
        starts_at: new Date(form.starts_at).toISOString(),
        ends_at: new Date(form.ends_at).toISOString(),
        capacity: form.capacity === '' ? null : Number(form.capacity),
        new_volunteer_slots: slots.filter((s) => s.title.trim()),
      })
      navigate(`/events/${event.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create event.')
    } finally {
      setSaving(false)
    }
  }

  if (communities.loading) return <p className="muted">Loading…</p>
  if (adminOf.length === 0) return <p className="muted">You need to be an admin of a community to create events.</p>

  return (
    <div className="narrow-wide">
      <h1>New event</h1>
      <label className="field-inline">Community
        <select value={community} onChange={set('community')}>
          {adminOf.map((c) => <option key={c.slug} value={c.slug}>{c.name}</option>)}
        </select>
      </label>

      <PasteToDraft community={community} onDraft={applyDraft} />

      <form className="card form" onSubmit={submit}>
        <h2>Event details</h2>
        <label>Title<input value={form.title} onChange={set('title')} placeholder="e.g. Timket Celebration" required /></label>
        <label>Description<textarea value={form.description} onChange={set('description')} rows={3} /></label>
        <label>Location<input value={form.location} onChange={set('location')} /></label>
        <div className="two-col">
          <label>Starts<input type="datetime-local" value={form.starts_at} onChange={set('starts_at')} required /></label>
          <label>Ends<input type="datetime-local" value={form.ends_at} onChange={set('ends_at')} required /></label>
        </div>
        <label>Capacity <span className="muted small">(leave empty for unlimited)</span>
          <input type="number" min={1} value={form.capacity} onChange={set('capacity')} />
        </label>

        <div>
          <p className="label">Volunteer slots</p>
          {slots.map((s, i) => (
            <div className="inline-form tight" key={i}>
              <input value={s.title} aria-label="Task"
                onChange={(e) => setSlots(slots.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)))} />
              <input type="number" min={1} value={s.spots_needed} aria-label="People needed"
                onChange={(e) => setSlots(slots.map((x, j) => (j === i ? { ...x, spots_needed: Number(e.target.value) } : x)))} />
              <button type="button" className="btn btn-ghost" onClick={() => setSlots(slots.filter((_, j) => j !== i))}>Remove</button>
            </div>
          ))}
          <button type="button" className="btn btn-outline tight-top"
            onClick={() => setSlots([...slots, { title: '', spots_needed: 1 }])}>+ Add slot</button>
        </div>

        <p className="muted small">Members of this community will get an email about this event.</p>
        {error && <p className="error">{error}</p>}
        <button className="btn btn-primary" disabled={saving}>{saving ? 'Creating…' : 'Create event'}</button>
      </form>
    </div>
  )
}

/** Paste the WhatsApp message you already wrote -> AI fills the form. */
function PasteToDraft({ community, onDraft }: { community: string; onDraft: (d: EventDraft) => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [missing, setMissing] = useState<string[] | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    setMissing(null)
    try {
      const draft = await api.draftEvent(community, text)
      onDraft(draft)
      setMissing(draft.missing)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read that message.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card ai-card">
      <div className="row">
        <h2>✨ Paste your announcement</h2>
        <button type="button" className="btn btn-ghost small" onClick={() => setText(EXAMPLE)}>Try an example</button>
      </div>
      <p className="muted small">
        Already wrote it for WhatsApp? Paste it here and we'll fill in the form. You can check everything before saving.
      </p>
      <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="Selam all! Coffee ceremony after liturgy this Sunday at noon…" />
      <div className="row">
        <button type="button" className="btn btn-primary" disabled={busy || !text.trim()} onClick={run}>
          {busy ? 'Reading…' : 'Fill the form'}
        </button>
        {missing && (missing.length === 0
          ? <span className="chip chip-ok">Filled in. Please check the details below.</span>
          : <span className="chip chip-warn">Check: {missing.join(', ')}</span>)}
      </div>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
