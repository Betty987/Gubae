/** Date helpers. The API sends ISO strings in UTC offset form; the browser
 * shows them in the viewer's own time zone automatically. */

export function formatWhen(startIso: string, endIso: string) {
  const start = new Date(startIso)
  const end = new Date(endIso)
  const day = start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const t = (d: Date) => d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${day} · ${t(start)} – ${t(end)}`
}

export function dateBadge(iso: string) {
  const d = new Date(iso)
  return {
    month: d.toLocaleDateString(undefined, { month: 'short' }).toUpperCase(),
    day: d.getDate(),
  }
}

/** <input type="datetime-local"> wants "YYYY-MM-DDTHH:mm" in LOCAL time. */
export function toLocalInput(d: Date) {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function slugify(text: string) {
  return text.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 50)
}
