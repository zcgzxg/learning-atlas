import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseFrontmatter } from './lib/frontmatter.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const knowledgeDir = path.join(root, 'knowledge');
const siteDir = path.join(root, 'site');
const docsDir = path.join(siteDir, 'src', 'content', 'docs');
const generatedDir = path.join(siteDir, 'src', 'generated');
const config = JSON.parse(fs.readFileSync(path.join(root, 'scripts', 'site-config.json'), 'utf8'));
const base = config.base.replace(/\/$/, '');
const labelsFile = path.join(knowledgeDir, '_labels.json');
const labels = fs.existsSync(labelsFile) ? JSON.parse(fs.readFileSync(labelsFile, 'utf8')) : {};
const acronyms = {
  ai: 'AI',
  api: 'API',
  cli: 'CLI',
  css: 'CSS',
  db: '数据库',
  html: 'HTML',
  js: 'JavaScript',
  llm: '大模型',
  ml: '机器学习',
  ts: 'TypeScript',
  ui: 'UI',
  ux: 'UX',
};

const collator = new Intl.Collator('zh-Hans-CN');

function fallbackLabel(segment) {
  return acronyms[segment] ?? segment.replace(/-/g, ' ').replace(/^(.)/, (_, first) => first.toUpperCase());
}

function labelFor(rel) {
  return labels[rel] ?? fallbackLabel(rel.split('/').pop());
}

function collect(dir, rel = '') {
  if (!fs.existsSync(dir)) return [];
  const pages = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name.startsWith('_')) continue;
    const abs = path.join(dir, entry.name);
    const next = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      pages.push(...collect(abs, next));
    } else if (/\.(md|mdx)$/.test(entry.name)) {
      const raw = fs.readFileSync(abs, 'utf8');
      const parsed = parseFrontmatter(raw);
      if (parsed.error) throw new Error(`${next}: ${parsed.error}`);
      pages.push({
        abs,
        rel: next,
        slug: next.replace(/\.(md|mdx)$/, ''),
        data: parsed.data,
        raw,
      });
    }
  }
  return pages;
}

function buildSidebar(dir, rel = '') {
  if (!fs.existsSync(dir)) return [];
  const dirs = [];
  const files = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name.startsWith('_')) continue;
    const abs = path.join(dir, entry.name);
    const next = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      const items = buildSidebar(abs, next);
      if (items.length) dirs.push({ label: labelFor(next), collapsed: rel !== '', items });
    } else if (/\.(md|mdx)$/.test(entry.name)) {
      const parsed = parseFrontmatter(fs.readFileSync(abs, 'utf8'));
      files.push({
        label: parsed.data.title ?? entry.name.replace(/\.(md|mdx)$/, ''),
        slug: next.replace(/\.(md|mdx)$/, ''),
        order: Number(parsed.data.order ?? Number.MAX_SAFE_INTEGER),
      });
    }
  }

  dirs.sort((a, b) => collator.compare(a.label, b.label));
  files.sort((a, b) => a.order - b.order || collator.compare(a.label, b.label));
  return [...dirs, ...files.map(({ label, slug }) => ({ label, slug }))];
}

function countPages(dir) {
  return collect(dir).length;
}

function quote(value) {
  return JSON.stringify(String(value ?? ''));
}

if (!fs.existsSync(knowledgeDir)) {
  console.error('knowledge/ directory is missing');
  process.exit(1);
}

const pages = collect(knowledgeDir).sort((a, b) =>
  String(b.data.updated ?? '').localeCompare(String(a.data.updated ?? '')),
);
const sidebar = buildSidebar(knowledgeDir);

fs.rmSync(docsDir, { recursive: true, force: true });
fs.mkdirSync(docsDir, { recursive: true });
for (const page of pages) {
  const dest = path.join(docsDir, page.rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, page.raw, 'utf8');
}

fs.mkdirSync(generatedDir, { recursive: true });
fs.writeFileSync(path.join(generatedDir, 'sidebar.json'), `${JSON.stringify(sidebar, null, 2)}\n`, 'utf8');

const recent = pages.slice(0, 6);
const recentCards = recent
  .map((page) => {
    const description = [page.data.updated, page.data.description].filter(Boolean).join(' · ');
    return `  <LinkCard title={${quote(page.data.title ?? page.slug)}} href={${quote(`${base}/${page.slug}/`)}} description={${quote(description)}} />`;
  })
  .join('\n');

const topDirs = fs
  .readdirSync(knowledgeDir, { withFileTypes: true })
  .filter((entry) => entry.isDirectory() && !entry.name.startsWith('.') && !entry.name.startsWith('_'))
  .map((entry) => {
    const rel = entry.name;
    const count = countPages(path.join(knowledgeDir, entry.name));
    const first = pages.find((page) => page.slug.startsWith(`${rel}/`));
    return { rel, label: labelFor(rel), count, first };
  })
  .filter((item) => item.count > 0 && item.first)
  .sort((a, b) => collator.compare(a.label, b.label));

const categoryCards = topDirs
  .map(
    (item) =>
      `  <LinkCard title={${quote(item.label)}} href={${quote(`${base}/${item.first.slug}/`)}} description={${quote(`${item.count} 篇笔记`)}} />`,
  )
  .join('\n');

const emptyState =
  pages.length === 0
    ? `\n${config.tagline}\n\n还没有笔记。在 OpenCode 中输入 \`/learn <主题>\` 开始。\n`
    : `\n${config.tagline}\n\n## 最近更新\n\n<CardGrid>\n${recentCards}\n</CardGrid>\n\n## 知识分类\n\n<CardGrid>\n${categoryCards}\n</CardGrid>\n\n共 ${pages.length} 篇笔记，持续更新。\n`;

const index = `---
title: ${quote(config.title)}
description: ${quote(config.tagline)}
---

import { CardGrid, LinkCard } from '@astrojs/starlight/components';
${emptyState}`;

fs.writeFileSync(path.join(docsDir, 'index.mdx'), index, 'utf8');

console.log(`Synced ${pages.length} note(s) and ${topDirs.length} categories to site/src/content/docs`);
