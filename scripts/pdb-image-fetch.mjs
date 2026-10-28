import fs from 'fs';
const url = process.argv[2];
const outPath = process.argv[3];
const resp = await fetch(url);
if (!resp.ok) { console.error('HTTP', resp.status); process.exit(1); }
const buf = Buffer.from(await resp.arrayBuffer());
fs.writeFileSync(outPath, buf);
console.log('saved', buf.length, 'bytes to', outPath);
