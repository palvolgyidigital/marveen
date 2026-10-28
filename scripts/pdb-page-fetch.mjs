import fs from 'fs';
const url = process.argv[2];
const outPath = process.argv[3];
const resp = await fetch(url);
if (!resp.ok) { console.error('HTTP', resp.status); process.exit(1); }
const text = await resp.text();
fs.writeFileSync(outPath, text);
console.log('saved', text.length, 'chars to', outPath);
