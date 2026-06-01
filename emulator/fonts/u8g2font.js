// Minimal u8g2 bitmap-font decoder — ports the glyph format from u8g2_font.c.
// Renders the exact device glyphs (crisp 1-bit), with per-glyph caching.
(function () {
  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  class U8g2Font {
    constructor(b64) {
      const f = b64ToBytes(b64);
      this.f = f;
      const s8 = v => (v >= 128 ? v - 256 : v);
      this.bp0  = f[2];  this.bp1  = f[3];
      this.bpcw = f[4];  this.bpch = f[5];
      this.bpcx = f[6];  this.bpcy = f[7];  this.bpd = f[8];
      this.maxW = f[9];  this.maxH = f[10];
      this.xOff = s8(f[11]); this.yOff = s8(f[12]);
      this.ascent = s8(f[13]);
      this.startA = (f[17] << 8) | f[18];
      this.starta = (f[19] << 8) | f[20];
      this._cache = new Map();
    }

    _findGlyph(enc) {
      const f = this.f;
      let p = 23;
      if (enc >= 97) p += this.starta;       // 'a'
      else if (enc >= 65) p += this.startA;  // 'A'
      for (;;) {
        if (f[p + 1] === 0) return -1;
        if (f[p] === enc) return p + 2;
        p += f[p + 1];
      }
    }

    // Returns { w, h, x, y, adv, bmp:Uint8Array(w*h) } or null
    glyph(enc) {
      if (this._cache.has(enc)) return this._cache.get(enc);
      const gp = this._findGlyph(enc);
      if (gp < 0) { this._cache.set(enc, null); return null; }
      const f = this.f;
      let p = gp, bit = 0;
      const ub = (cnt) => {
        if (cnt === 0) return 0;
        let val = f[p] >> bit, bpc = bit + cnt;
        if (bpc >= 8) { val |= f[p + 1] << (8 - bit); p++; bpc -= 8; }
        val &= (1 << cnt) - 1; bit = bpc; return val;
      };
      const sb = (cnt) => ub(cnt) - (1 << (cnt - 1));
      const w = ub(this.bpcw), h = ub(this.bpch);
      const x = sb(this.bpcx), y = sb(this.bpcy), adv = sb(this.bpd);
      const bmp = new Uint8Array(w * h);
      if (w > 0) {
        let lx = 0, ly = 0;
        for (;;) {
          const a = ub(this.bp0), b = ub(this.bp1);
          for (;;) {
            for (const [cnt, fg] of [[a, 0], [b, 1]]) {
              let rem = cnt;
              while (rem > 0) {
                const space = w - lx, cur = Math.min(rem, space);
                if (fg) for (let k = 0; k < cur; k++) if (ly < h) bmp[ly * w + lx + k] = 1;
                lx += cur; rem -= cur;
                if (lx >= w) { lx = 0; ly++; }
              }
            }
            if (ub(1) === 0) break;
          }
          if (ly >= h) break;
        }
      }
      const g = { w, h, x, y, adv, bmp };
      this._cache.set(enc, g);
      return g;
    }

    // Draw a glyph onto an ImageData-like {data,width} at baseline (penX, baseY),
    // color 255 (white) or 0 (black). Returns advance width.
    drawGlyph(buf, bufW, bufH, enc, penX, baseY, color) {
      const g = this.glyph(enc);
      if (!g) return this.maxW;
      const topX = penX + g.x;
      const topY = baseY - (g.h + g.y);   // u8g2: target_y -= h + y
      for (let row = 0; row < g.h; row++) {
        const py = topY + row;
        if (py < 0 || py >= bufH) continue;
        for (let col = 0; col < g.w; col++) {
          if (!g.bmp[row * g.w + col]) continue;
          const px = topX + col;
          if (px < 0 || px >= bufW) continue;
          const i = (py * bufW + px) * 4;
          buf[i] = buf[i + 1] = buf[i + 2] = color; buf[i + 3] = 255;
        }
      }
      return g.adv;
    }
  }

  window.U8g2Font = U8g2Font;
})();
