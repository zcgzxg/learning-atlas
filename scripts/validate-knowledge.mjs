import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFrontmatter } from './lib/frontmatter.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const knowledgeDir = path.join(root, 'knowledge');
const slugSegment = /^[a-z0-9][a-z0-9-]*$/;
const errors = [];
const warnings = [];

function walk(dir, rel = '') {
  if (!fs.existsSync(dir)) return [];
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name.startsWith('_')) continue;
    const abs = path.join(dir, entry.name);
    const next = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) files.push(...walk(abs, next));
    else if (/\.(md|mdx)$/.test(entry.name)) files.push({ abs, rel: next });
  }
  return files;
}

if (!fs.existsSync(knowledgeDir)) {
  console.error('knowledge/ directory is missing');
  process.exit(1);
}

const pages = walk(knowledgeDir);
if (pages.length === 0) {
  warnings.push('knowledge/ contains no pages yet');
}

const titles = new Map();

for (const page of pages) {
  const slug = page.rel.replace(/\.(md|mdx)$/, '');
  const segments = slug.split('/');
  for (const segment of segments) {
    if (!slugSegment.test(segment)) {
      errors.push(`${page.rel}: path segment "${segment}" must be lowercase kebab-case`);
    }
  }

  const raw = fs.readFileSync(page.abs, 'utf8');
  const { data, body, error } = parseFrontmatter(raw);
  if (error) {
    errors.push(`${page.rel}: ${error}`);
    continue;
  }
  if (typeof data.title !== 'string' || !data.title.trim()) {
    errors.push(`${page.rel}: frontmatter "title" is required`);
  } else if (data.title.length > 80) {
    errors.push(`${page.rel}: "title" must be at most 80 characters`);
  }
  if (data.description !== undefined && typeof data.description !== 'string') {
    errors.push(`${page.rel}: "description" must be a string`);
  }
  if (data.tags !== undefined && (!Array.isArray(data.tags) || data.tags.some((tag) => typeof tag !== 'string'))) {
    errors.push(`${page.rel}: "tags" must be an array of strings`);
  }
  if (data.updated !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(String(data.updated))) {
    errors.push(`${page.rel}: "updated" must use YYYY-MM-DD`);
  }
  if (!body.trim()) {
    errors.push(`${page.rel}: body is empty`);
  }
  if (!/^##\s+/m.test(body)) {
    warnings.push(`${page.rel}: body has no level-2 section`);
  }

  if (typeof data.title === 'string') {
    const key = data.title.trim();
    if (titles.has(key)) warnings.push(`${page.rel}: duplicate title "${key}" (also ${titles.get(key)})`);
    else titles.set(key, page.rel);
  }
}

for (const warning of warnings) console.warn(`warning: ${warning}`);
for (const error of errors) console.error(`error: ${error}`);

if (errors.length > 0) {
  console.error(`\n${errors.length} error(s), ${warnings.length} warning(s)`);
  process.exit(1);
}

console.log(`Validated ${pages.length} note(s), ${warnings.length} warning(s)`);
