// figure_reader.js for figures already shown on a Packing Center page: same components,
// read from the page's own <img> elements by file name, several at once.
((names) => JSON.stringify(names.map((name) => {
  const img = [...document.images].find((i) => i.getAttribute("src") === name);
  const w = img.naturalWidth, h = img.naturalHeight;
  const canvas = document.createElement("canvas");
  canvas.width = w; canvas.height = h;
  const g = canvas.getContext("2d");
  g.drawImage(img, 0, 0);
  const d = g.getImageData(0, 0, w, h).data;
  const rgb = (i) => [d[4 * i], d[4 * i + 1], d[4 * i + 2], d[4 * i + 3]];
  const counts = new Map();
  for (let i = 0; i < w * h; i++) {
    const [r, gr, b, a] = rgb(i);
    if (a < 128 || r + gr + b > 720 || r + gr + b < 200) continue;
    const key = `${r},${gr},${b}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const fill = [...counts].sort((p, q) => q[1] - p[1])[0][0].split(",").map(Number);
  const isFill = (i) => {
    const [r, gr, b, a] = rgb(i);
    return a >= 128 && Math.abs(r - fill[0]) + Math.abs(gr - fill[1]) + Math.abs(b - fill[2]) < 60;
  };
  const seen = new Uint8Array(w * h), comps = [];
  for (let s = 0; s < w * h; s++) {
    if (seen[s] || !isFill(s)) continue;
    const stack = [s], pts = [];
    seen[s] = 1;
    while (stack.length) {
      const i = stack.pop(), x = i % w, y = (i / w) | 0;
      pts.push([x, y]);
      for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
        const X = x + dx, Y = y + dy;
        if (X < 0 || Y < 0 || X >= w || Y >= h) continue;
        const j = Y * w + X;
        if (!seen[j] && isFill(j)) { seen[j] = 1; stack.push(j); }
      }
    }
    if (pts.length < 8) continue;
    const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length + 0.5;
    const cy = pts.reduce((a, p) => a + p[1], 0) / pts.length + 0.5;
    let best = [Infinity, 0];
    for (let t = 0; t < 90; t += 0.25) {
      const a = t * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
      let u0 = Infinity, u1 = -Infinity, v0 = Infinity, v1 = -Infinity;
      for (const [x, y] of pts) {
        const u = x * ca + y * sa, v = -x * sa + y * ca;
        if (u < u0) u0 = u; if (u > u1) u1 = u; if (v < v0) v0 = v; if (v > v1) v1 = v;
      }
      const area = (u1 - u0 + 1) * (v1 - v0 + 1);
      if (area < best[0]) best = [area, t];
    }
    comps.push([+cx.toFixed(2), +cy.toFixed(2), best[1], pts.length]);
  }
  return { file: name, w, h, fill, comps };
})))
