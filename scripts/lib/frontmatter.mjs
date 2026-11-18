/**
 * Minimal frontmatter parser shared by the site build and knowledge validation.
 * The knowledge format is deliberately simple: one-line YAML values, with JSON
 * strings / arrays for values that need escaping.
 */
export function parseFrontmatter(raw) {
  const text = raw.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
  if (!text.startsWith('---\n')) {
    return { data: {}, body: text, error: 'missing frontmatter block' };
  }

  const end = text.indexOf('\n---', 4);
  if (end === -1) {
    return { data: {}, body: text, error: 'unterminated frontmatter block' };
  }

  const yaml = text.slice(4, end);
  const after = text.slice(end + 4);
  const body = after.startsWith('\n') ? after.slice(1) : after;
  const data = {};

  for (const line of yaml.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const colon = trimmed.indexOf(':');
    if (colon === -1) continue;
    const key = trimmed.slice(0, colon).trim();
    const value = trimmed.slice(colon + 1).trim();
    if (!key || !value) continue;
    if (value.startsWith('"') || value.startsWith('[') || value.startsWith('{')) {
      try {
        data[key] = JSON.parse(value);
        continue;
      } catch {
        // fall through to a plain string
      }
    }
    if (value === 'true' || value === 'false') {
      data[key] = value === 'true';
      continue;
    }
    data[key] = value;
  }

  return { data, body, error: null };
}
