// The Convert button as an Oblivion gate, using the Remastered splash art's own painted fire.
// Real flames are kept alive with a rising heat-haze warp (no made-up noise fire).
//   fire-glow.jpg : the hot mouth inside the button
//   fire-gate.webp: the burning gate, bent to the stitched sign's exact outline (same frame as gate.png)
//   gate-hole.png : the gate's mouth, for the red glow
(() => {
  const cv = document.getElementById('fire');
  const go = document.getElementById('go');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const api = { place() {}, set() {}, idle() {}, ok: false };
  window.Fire = api;
  const gl = cv && cv.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false });
  if (!gl) { go.classList.add('nogl'); return; }

  const vs = `attribute vec2 a; void main(){ gl_Position = vec4(a, 0., 1.); }`;
  const fs = `
precision highp float;
uniform vec2 uRes, uPx;   // the canvas in css px, and in real pixels
uniform float uTime, uHeat, uGate;
uniform vec4 uBtn;        // button centre and half size, css px, y down
uniform sampler2D tGlow, tGate, tHole;

float hash(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p), u = f * f * (3. - 2. * f);
  return mix(mix(hash(i), hash(i + vec2(1., 0.)), u.x), mix(hash(i + vec2(0., 1.)), hash(i + vec2(1., 1.)), u.x), u.y);
}
float fbm(vec2 p){ float v = 0., a = .5; for (int i = 0; i < 3; i++){ v += a * noise(p); p = p * 2.03 + 11.3; a *= .5; } return v; }
// heat haze: a warp field that drifts upward
vec2 haze(vec2 p, float sc, float sp){
  return vec2(fbm(vec2(p.x * sc, p.y * sc + uTime * sp)), fbm(vec2(p.x * sc + 5.2, p.y * sc + uTime * sp + 1.7))) - .5;
}
float sdPill(vec2 p, vec2 b){ float r = b.y; vec2 q = abs(p) - b + r; return length(max(q, 0.)) + min(max(q.x, q.y), 0.) - r; }
vec4 tex(sampler2D t, vec2 uv){
  float inside = step(0., uv.x) * step(uv.x, 1.) * step(0., uv.y) * step(uv.y, 1.);
  return texture2D(t, clamp(uv, 0., 1.)) * inside;
}

void main(){
  vec2 p = vec2(gl_FragCoord.x, uPx.y - gl_FragCoord.y) * uRes / uPx;
  vec2 q = p - uBtn.xy;
  float d = sdPill(q, uBtn.zw);
  float T = uTime;
  vec3 col = vec3(0.); float a = 0.;

  // red light the gate throws on the stone
  float g = exp(-max(d, 0.) / 26.) * (.1 + .26 * uHeat) * smoothstep(-2., 2., d);
  col = vec3(.75, .12, .03) * g; a = g;

  // the burning gate: climbs from the tips of the arms up to the top bar
  if (uGate > .001) {
    vec2 gp = p / uRes;                                      // the canvas is the sign's own frame
    float edge = (1. - gp.y) - uGate * 1.3 + (fbm(vec2(gp.x * 6., gp.y * 4. - T)) - .5) * .3;
    float m = smoothstep(.1, -.05, edge);
    // the mouth of the gate glows once the arms have caught
    vec3 hg = texture2D(tGlow, clamp(vec2(gp.x, .1 + gp.y * .8) + haze(p, .02, .5) * .14, 0., 1.)).rgb;
    float hl = dot(hg, vec3(.3, .6, .1));
    float ha = texture2D(tHole, gp).r * smoothstep(.55, 1., uGate) * (.2 + .3 * hl);
    col = col * (1. - ha) + mix(vec3(.3, .02, .0), vec3(.95, .2, .03), smoothstep(.35, 1., hl)) * ha; a = a * (1. - ha) + ha;
    vec2 w = haze(p, .035, 1.6) * vec2(.012, .022) * (1.25 - gp.y);
    vec4 t = tex(tGate, gp + w);
    float flick = .82 + .36 * fbm(vec2(T * 3.1, gp.y * 5. + gp.x * 2.));
    float ta = t.a * m;
    // soft light around the flames
    float halo = 0.;
    for (int i = 0; i < 4; i++) {
      float ang = float(i) * 1.5708 + .6;
      halo += tex(tGate, gp + vec2(cos(ang), sin(ang)) * .035).a;
    }
    halo *= .13 * m * uGate;
    col = col * (1. - halo) + vec3(.8, .16, .03) * halo; a = a * (1. - halo) + halo;
    vec3 tc = t.rgb * flick * ta * uGate;
    ta *= uGate;
    col = col * (1. - ta) + tc; a = a * (1. - ta) + ta;
  }

  // the hot mouth of the gate inside the button
  float pa = smoothstep(.75, -.75, d);
  if (pa > 0.) {
    vec2 ip = q / (uBtn.zw * 2.) + .5;
    vec2 w = haze(p, .04, 1.2) * .09;
    vec3 gc = texture2D(tGlow, clamp(vec2(.08 + ip.x * .84, .15 + ip.y * .7) + w + vec2(.03 * sin(T * .4), 0.), 0., 1.)).rgb;
    float lit = mix(.5, .95, uHeat) * (.88 + .24 * fbm(vec2(T * 1.7, ip.x * 3.)));
    // grade toward deep red when calm, toward yellow fire when it burns
    float hot = clamp(uHeat, 0., 1.);
    float L = dot(gc, vec3(.3, .6, .1));
    vec3 ember = mix(vec3(.3, .02, .01), vec3(1., .3, .05), smoothstep(.35, 1., L));
    gc = mix(ember, gc, hot * hot * .6);
    // shade toward red, never toward brown: green and blue fall off faster than red
    float s = clamp(lit * mix(.4, 1., smoothstep(0., -13., d)) * mix(1.08, .72, ip.y), 0., 1.);
    gc = vec3(gc.r * (.5 + .5 * s), gc.g * s * (.3 + .7 * s), gc.b * s * s * s);
    col = col * (1. - pa) + gc * pa; a = a * (1. - pa) + pa;
  }
  gl_FragColor = vec4(col, a);
}`;

  function sh(type, src) {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  let prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
  } catch (e) { console.warn('fire off:', e); go.classList.add('nogl'); return; }
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'a');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = n => gl.getUniformLocation(prog, n);
  const u = { res: U('uRes'), px: U('uPx'), time: U('uTime'), heat: U('uHeat'), gate: U('uGate'), btn: U('uBtn') };

  function texture(unit, name, src) {
    const t = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]));
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    gl.uniform1i(U(name), unit);
    const img = new Image();
    img.onload = () => {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      draw();
    };
    img.src = src;
  }
  texture(1, 'tGlow', 'assets/fire-glow.jpg');
  texture(2, 'tGate', 'assets/fire-gate.webp');
  texture(3, 'tHole', 'assets/gate-hole.png');

  const IDLE = { heat: .32, gate: 0 };
  const cur = { ...IDLE }, tgt = { ...IDLE };
  let box = null, t0 = performance.now(), last = t0;
  // The fire needs about 60 pictures a second. Screens can ask for 240 or more, so frames in between
  // are skipped, and it runs at half speed while another window (a game) is in front.
  const GAP_FRONT = 1000 / 60 - 2, GAP_BEHIND = 1000 / 30 - 2;

  function draw(now = performance.now()) {
    if (!box) return;
    gl.viewport(0, 0, cv.width, cv.height);
    gl.uniform2f(u.res, box.w, box.h);
    gl.uniform2f(u.px, cv.width, cv.height);
    gl.uniform1f(u.time, reduce ? 3 : (now - t0) / 1000);
    gl.uniform1f(u.heat, cur.heat);
    gl.uniform1f(u.gate, box.narrow ? 0 : cur.gate);
    gl.uniform4f(u.btn, box.bx, box.by, box.bw / 2, box.bh / 2);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden || now - last < (document.hasFocus() ? GAP_FRONT : GAP_BEHIND)) return;
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    for (const k of ['heat', 'gate']) {
      const rate = tgt[k] > cur[k] ? (k === 'gate' ? 2.6 : 5) : 1.3;   // catches fast, dies down slowly
      cur[k] += (tgt[k] - cur[k]) * (1 - Math.exp(-dt * rate));
    }
    draw(now);
  }

  api.place = b => {
    box = b;                                                     // the page places and sizes the canvas itself
    const dpr = Math.min(devicePixelRatio || 1, 2);
    const pw = Math.round(b.w * dpr), ph = Math.round(b.h * dpr);
    if (cv.width !== pw || cv.height !== ph) { cv.width = pw; cv.height = ph; }
    cv.classList.add('on');
    draw();
  };
  api.set = t => { Object.assign(tgt, t); if (reduce) { Object.assign(cur, tgt); draw(); } };
  api.idle = () => api.set(IDLE);
  api.snap = () => { Object.assign(cur, tgt); draw(); };       // jump straight to the target (for screenshots)
  api.ok = true;
  if (!reduce) requestAnimationFrame(frame);
})();
