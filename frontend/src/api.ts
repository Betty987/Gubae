/**
 * The ONLY file that talks to the backend.
 *
 * Every page calls functions from here instead of using fetch() directly, so:
 *  - the JWT is attached to every request in one place
 *  - expired access tokens are refreshed automatically in one place
 *  - errors are turned into readable messages in one place
 */

// ---------- Types: these mirror the JSON from the Django serializers ----------
export type Role = 'admin' | 'member'
export type RSVPStatus = 'going' | 'maybe' | 'not_going'

export interface User {
  id: number
  username: string
  email: string
  first_name: string
  last_name: string
}

export interface Community {
  id: number
  name: string
  slug: string
  description: string
  member_count: number
  my_role: Role | null
  notify_new_events: boolean | null // my email setting (null if not a member)
}

export interface VolunteerSlot {
  id: number
  title: string
  spots_needed: number
  spots_filled: number
  signed_up: boolean
}

export interface Event {
  id: number
  community: string // slug
  community_name: string
  title: string
  description: string
  location: string
  starts_at: string // ISO 8601 date string
  ends_at: string
  capacity: number | null
  going_count: number
  spots_left: number | null
  my_rsvp: RSVPStatus | null
  can_manage: boolean
  volunteer_slots: VolunteerSlot[]
}

/** What the AI extracted from a pasted announcement. Nothing is saved yet. */
export interface EventDraft {
  community: string
  title: string
  description: string
  location: string
  starts_at: string | null
  ends_at: string | null
  capacity: number | null
  volunteer_slots: { title: string; spots_needed: number }[]
  missing: string[]
}

export type NewEvent = Partial<Omit<Event, 'volunteer_slots'>> & {
  new_volunteer_slots?: { title: string; spots_needed: number }[]
}

export interface Attendee {
  username: string
  name: string
  status: RSVPStatus
  created_at: string
}

interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

// ---------- Token storage ----------
// Design decision: tokens live in localStorage. Simple and survives refresh.
// Tradeoff: any JavaScript on the page (e.g. an XSS bug) could read them.
// The more secure option is an httpOnly cookie set by the server, which JS
// can't read at all. Worth saying out loud in an interview.
const ACCESS = 'gubae.access'
const REFRESH = 'gubae.refresh'

export const tokens = {
  get access() { return localStorage.getItem(ACCESS) },
  get refresh() { return localStorage.getItem(REFRESH) },
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS, access)
    if (refresh) localStorage.setItem(REFRESH, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** DRF errors come in a few shapes; flatten them into one readable sentence. */
function errorMessage(body: unknown): string {
  if (!body || typeof body !== 'object') return 'Something went wrong.'
  if ('detail' in body) return String((body as { detail: unknown }).detail)
  if (Array.isArray(body)) return body.join(' ')
  return Object.entries(body as Record<string, unknown>)
    .map(([field, msgs]) => {
      const text = Array.isArray(msgs) ? msgs.join(' ') : String(msgs)
      return field === 'non_field_errors' ? text : `${field.replace('_', ' ')}: ${text}`
    })
    .join(' ')
}

/** Exchange the refresh token for a new access token. Returns false if that fails. */
async function refreshAccessToken(): Promise<boolean> {
  const refresh = tokens.refresh
  if (!refresh) return false
  const res = await fetch('/api/auth/token/refresh/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
  })
  if (!res.ok) return false
  const data = await res.json()
  tokens.set(data.access)
  return true
}

/**
 * fetch() + JWT + auto-refresh.
 * Flow: send with access token -> if 401, refresh once and retry -> if still
 * 401, the session is over (clear tokens, caller shows the login page).
 */
async function request<T>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (tokens.access) headers.set('Authorization', `Bearer ${tokens.access}`)

  const res = await fetch(`/api${path}`, { ...options, headers })

  if (res.status === 401 && tokens.refresh && !retried) {
    if (await refreshAccessToken()) return request<T>(path, options, true)
    tokens.clear()
  }
  if (res.status === 204) return undefined as T // No Content
  const body = await res.json().catch(() => null)
  if (!res.ok) throw new ApiError(res.status, errorMessage(body))
  return body as T
}

const post = <T>(path: string, data?: unknown) =>
  request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })

// ---------- The API, one function per endpoint ----------
export const api = {
  // auth
  async login(username: string, password: string) {
    const data = await post<{ access: string; refresh: string }>('/auth/token/', { username, password })
    tokens.set(data.access, data.refresh)
  },
  register: (data: { username: string; email: string; password: string; first_name?: string; last_name?: string }) =>
    post<User>('/auth/register/', data),
  me: () => request<User>('/auth/me/'),

  // communities
  communities: () => request<Page<Community>>('/communities/').then((p) => p.results),
  createCommunity: (data: { name: string; slug: string; description: string }) =>
    post<Community>('/communities/', data),
  join: (slug: string) => post<{ role: Role }>(`/communities/${slug}/membership/`),
  leave: (slug: string) => request<void>(`/communities/${slug}/membership/`, { method: 'DELETE' }),
  setNotify: (slug: string, notify_new_events: boolean) =>
    request(`/communities/${slug}/membership/`, { method: 'PATCH', body: JSON.stringify({ notify_new_events }) }),

  // events
  events(params: { community?: string; upcoming?: boolean } = {}) {
    const q = new URLSearchParams()
    if (params.community) q.set('community', params.community)
    if (params.upcoming) q.set('upcoming', 'true')
    return request<Page<Event>>(`/events/?${q}`).then((p) => p.results)
  },
  event: (id: number) => request<Event>(`/events/${id}/`),
  createEvent: (data: NewEvent) => post<Event>('/events/', data),
  draftEvent: (community: string, text: string) => post<EventDraft>('/events/draft/', { community, text }),
  deleteEvent: (id: number) => request<void>(`/events/${id}/`, { method: 'DELETE' }),
  rsvp: (id: number, status: RSVPStatus) => post(`/events/${id}/rsvp/`, { status }),
  cancelRsvp: (id: number) => request<void>(`/events/${id}/rsvp/`, { method: 'DELETE' }),
  attendees: (id: number) => request<Attendee[]>(`/events/${id}/attendees/`),
  addSlot: (id: number, title: string, spots_needed: number) =>
    post<VolunteerSlot>(`/events/${id}/volunteer-slots/`, { title, spots_needed }),
  volunteer: (slotId: number) => post(`/volunteer-slots/${slotId}/signup/`),
  unvolunteer: (slotId: number) => request<void>(`/volunteer-slots/${slotId}/signup/`, { method: 'DELETE' }),
}

// ---------- Calendar feeds (plain URLs, not JSON) ----------
/** Absolute URL a calendar app can subscribe to. */
export const communityCalendarUrl = (slug: string) =>
  `${window.location.origin}/api/communities/${slug}/calendar.ics`
/** webcal:// makes phones open "Subscribe to calendar?" directly. */
export const webcalUrl = (httpUrl: string) => httpUrl.replace(/^https?:/, 'webcal:')
export const eventCalendarUrl = (id: number) => `/api/events/${id}/calendar.ics`
