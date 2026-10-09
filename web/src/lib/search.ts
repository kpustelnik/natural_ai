// Search over everything that has an id or a name. Scoring is simple and predictable:
// exact id > id prefix > word prefix in the name > substring anywhere.

export interface SearchItem {
  key: string; // unique, e.g. building:D-17
  id: string; // shown in bold, e.g. D-17
  label: string; // secondary text, e.g. the name
  group: string; // Buildings, Stops, Other buildings
  terms: string[]; // searchable strings (id first)
}

function norm(s: string): string {
  return s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");
}

function compact(s: string): string {
  return norm(s).replace(/[\s\-_/.]/g, "");
}

export function score(item: SearchItem, query: string): number {
  const q = norm(query.trim());
  if (!q) return 0;
  const qc = compact(query);
  let best = 0;
  item.terms.forEach((term, i) => {
    const t = norm(term);
    const weight = i === 0 ? 1 : 0.8;
    let s = 0;
    if (t === q || compact(term) === qc) s = 100;
    else if (t.startsWith(q) || compact(term).startsWith(qc)) s = 80;
    else if (t.split(/[\s\-/]+/).some((w) => w.startsWith(q))) s = 60;
    else if (t.includes(q)) s = 40;
    best = Math.max(best, s * weight);
  });
  return best;
}

export function search(items: SearchItem[], query: string, limit = 12): SearchItem[] {
  return items
    .map((item) => ({ item, s: score(item, query) }))
    .filter((r) => r.s > 0)
    .sort((a, b) => b.s - a.s || a.item.id.localeCompare(b.item.id, "en", { numeric: true }))
    .slice(0, limit)
    .map((r) => r.item);
}
