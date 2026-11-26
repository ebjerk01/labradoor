// A small markdown subset → plain data, rendered by Md.svelte with ordinary elements (never {@html}): model text can
// quote logs, titles and notes written by anyone, so nothing in it may become markup. Links go through safeUrl.
// Blocks: paragraphs, # headings, - / 1. lists, ``` code, | tables, > quotes. Inline: `code`, **bold**, *em*, [t](url).

export function inline(s) {
  const out = [];
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|(\[[^\]\n]{1,200}\]\([^)\s]{1,500}\))/g;
  let i = 0, m;
  while ((m = re.exec(s))) {
    if (m.index > i) out.push({ t: 'text', v: s.slice(i, m.index) });
    const x = m[0];
    if (m[1]) out.push({ t: 'code', v: x.slice(1, -1) });
    else if (m[2]) out.push({ t: 'b', v: x.slice(2, -2) });
    else if (m[3]) out.push({ t: 'i', v: x.slice(1, -1) });
    else {
      const k = x.indexOf('](');
      out.push({ t: 'a', v: x.slice(1, k), href: x.slice(k + 2, -1) });
    }
    i = m.index + x.length;
  }
  if (i < s.length) out.push({ t: 'text', v: s.slice(i) });
  return out;
}

export function parse(src) {
  const lines = String(src || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];
  let para = [];
  // a paragraph keeps its line breaks (the summary's status lines; Md.svelte renders p with pre-line)
  const flush = () => { if (para.length) { blocks.push({ t: 'p', v: inline(para.join('\n')) }); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*```/.test(l)) {
      flush();
      const code = [];
      for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
      blocks.push({ t: 'code', v: code.join('\n') });
      continue;
    }
    if (!l.trim()) { flush(); continue; }
    let m;
    if ((m = /^(#{1,4})\s+(.*)$/.exec(l))) { flush(); blocks.push({ t: 'h', level: m[1].length, v: inline(m[2]) }); continue; }
    if (/^\s*\|.*\|\s*$/.test(l)) {
      flush();
      const rows = [];
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) {
        if (/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) continue;  // the --- separator row
        rows.push(lines[i].trim().slice(1, -1).split('|').map((c) => inline(c.trim())));
      }
      i--;
      blocks.push({ t: 'table', rows });
      continue;
    }
    if ((m = /^\s*([-*•]|\d{1,3}[.)])\s+(.*)$/.exec(l))) {
      flush();
      const ordered = /\d/.test(m[1]);
      const items = [];
      for (; i < lines.length; i++) {
        const x = /^\s*([-*•]|\d{1,3}[.)])\s+(.*)$/.exec(lines[i]);
        if (x && /\d/.test(x[1]) === ordered) items.push(x[2]);
        else if (items.length && /^\s{2,}\S/.test(lines[i])) items[items.length - 1] += ' ' + lines[i].trim();
        else break;
      }
      i--;
      blocks.push({ t: ordered ? 'ol' : 'ul', items: items.map(inline) });
      continue;
    }
    if ((m = /^\s*>\s?(.*)$/.exec(l))) { flush(); blocks.push({ t: 'quote', v: inline(m[1]) }); continue; }
    para.push(l.trim());
  }
  flush();
  return blocks;
}
