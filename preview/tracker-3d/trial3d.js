/* Trial only: 3D hole and 3D green laid over the real Round Tracker page.
   Reads the tracker's own state (hole, bookView, pins, balls, puttGeom, CADDY). */
(function boot() {
  if (!window.__t3ctx || !window.THREE) { setTimeout(boot, 60); return; }
  const X = window.__t3ctx, zdata = X.zdata, zAt = X.zAt, puttGeom = X.puttGeom, BOOK = X.BOOK, CADDY = X.CADDY;
  const FT = 3.28084, YD = 0.9144, calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const b64 = s => { const r = atob(s), a = new Uint8Array(r.length); for (let i = 0; i < r.length; i++) a[i] = r.charCodeAt(i); return a; };
  const css = document.createElement('style');
  css.textContent = `.t3-frame{position:relative;border-radius:10px;overflow:hidden;background:linear-gradient(#8FB7DC 0%,#CFE0EC 55%,#E9EEE9 100%);touch-action:none}
  .t3-frame canvas{display:block;width:100%;height:100%}
  .t3-hole{height:min(64vh,540px)} .t3-green{height:290px;margin-bottom:10px}
  .t3-chip{position:absolute;left:50%;top:8px;transform:translateX(-50%);background:rgba(12,35,64,.88);color:#fff;font-family:'Spline Sans Mono',ui-monospace,monospace;font-size:11.5px;font-weight:700;padding:4px 11px;border-radius:999px;white-space:nowrap;pointer-events:none}
  .t3-row{display:flex;gap:6px;justify-content:center;flex-wrap:wrap;padding:8px 10px;background:#EDE7DA;border-bottom:1px solid rgba(11,33,52,.1)}
  .t3-row.sub{background:none;border:0;padding:8px 0 0}
  .t3-pill{font-family:'Spline Sans Mono',ui-monospace,monospace;font-size:11.5px;font-weight:700;padding:6px 13px;border-radius:999px;border:1px solid #1F4E9D;color:#1F4E9D;background:transparent;cursor:pointer;-webkit-tap-highlight-color:transparent}
  .t3-pill.on{background:#1F4E9D;color:#fff} .t3-row.sub .t3-pill{font-size:10.5px;padding:5px 11px}
  .t3-read{font-family:'Spline Sans Mono',ui-monospace,monospace;font-size:13px;font-weight:700;color:#0C2340;text-align:center;padding:10px 4px 0}
  .t3-note{font-family:Barlow,sans-serif;font-size:12px;color:#5C6B82;text-align:center;padding:6px 8px 0;line-height:1.45}
  .book.t3on #fwlayers{display:none!important}`;
  document.head.appendChild(css);

  function stage(box) {
    const W = box.clientWidth || 340, Hh = box.clientHeight || 300;
    const r = new THREE.WebGLRenderer({ antialias: true, alpha: true }); r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.setSize(W, Hh, false); box.appendChild(r.domElement);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f7a, 1.25)); const sun = new THREE.DirectionalLight(0xfff4e0, 1.7); sun.position.set(-.6, 1, .35); scene.add(sun);
    const cam = new THREE.PerspectiveCamera(42, W / Hh, 1, 4000);
    const fit = () => { const w = box.clientWidth, h = box.clientHeight; if (w && h) { r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); } };
    return { r, scene, cam, fit };
  }
  const tex = src => { const t = new THREE.TextureLoader().load(src); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t; };
  function flagAt(parent, p, h) {
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(h * .012, h * .012, h), new THREE.MeshBasicMaterial({ color: 0xffffff })); pole.position.copy(p).y += h / 2; parent.add(pole);
    const f = new THREE.Mesh(new THREE.PlaneGeometry(h * .36, h * .22), new THREE.MeshBasicMaterial({ color: 0xB22234, side: THREE.DoubleSide })); f.position.copy(p).add(new THREE.Vector3(h * .18, h * .88, 0)); parent.add(f);
  }
  function label(text, size) {
    const c = document.createElement('canvas'), x = c.getContext('2d'); x.font = "700 44px 'Spline Sans Mono', ui-monospace, monospace";
    c.width = Math.ceil(x.measureText(text).width) + 24; c.height = 60; x.font = "700 44px 'Spline Sans Mono', ui-monospace, monospace";
    x.lineWidth = 9; x.strokeStyle = '#0C2340'; x.lineJoin = 'round'; x.strokeText(text, 12, 45); x.fillStyle = '#fff'; x.fillText(text, 12, 45);
    const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false, transparent: true })); s.scale.set(size * c.width / c.height, size, 1); s.renderOrder = 5; return s;
  }

  /* ------------------------------ whole hole ------------------------------ */
  const dataCache = {};
  const loadHole = n => dataCache[n] || (dataCache[n] = fetch(`h3d/hole${n}.json`).then(r => r.json()));
  let clubIdx = 0, show = { rings: true, trees: true };

  function makeHole(n) {
    const EX = 1.5, el = document.createElement('div'); let alive = true, kill = () => {};
    el.innerHTML = `<div class="t3-row" data-r="clubs"></div><div style="padding:10px 10px 12px"><div class="t3-frame t3-hole"><div class="t3-chip">Loading hole ${n}</div></div>
      <div class="t3-row sub" data-r="cams"><button class="t3-pill on" data-c="tee" type="button">From the tee</button><button class="t3-pill" data-c="top" type="button">Overhead</button><button class="t3-pill" data-c="green" type="button">From the green</button></div>
      <div class="t3-row sub" data-r="lay"><button class="t3-pill" data-l="rings" type="button">Yardage</button><button class="t3-pill" data-l="trees" type="button">Trees</button></div>
      <div class="t3-read" data-r="a"></div><div class="t3-read" data-r="b" style="padding-top:2px"></div>
      <div class="t3-note">Drag to spin, pinch to zoom, two fingers to slide. Ground and tree heights from USGS lidar (2020), drawn ${EX} times real height. Houses built since then show flat. The landing oval is a general size, not your dispersion yet.</div></div>`;
    const q = s => el.querySelector(s), box = q('.t3-hole');
    loadHole(n).then(d => { if (!alive) return;
      q('.t3-chip').textContent = `${d.yd} to green`;
      const { r, scene, cam, fit } = stage(box); scene.fog = new THREE.Fog(0xCFE0EC, 380, 1300);
      const g8 = b64(d.g), h8 = b64(d.h), nx = d.nx, ny = d.ny, c = d.cell;
      const ground = (x, y) => { let u = (x - d.x0) / c, v = (d.y1 - y) / c; u = Math.max(0, Math.min(nx - 1.001, u)); v = Math.max(0, Math.min(ny - 1.001, v));
        const i = u | 0, j = v | 0, fu = u - i, fv = v - j, k = j * nx + i;
        return (g8[k] * (1 - fu) * (1 - fv) + g8[k + 1] * fu * (1 - fv) + g8[k + nx] * (1 - fu) * fv + g8[k + nx + 1] * fu * fv) * d.gs; };
      const inside = (x, y) => x > d.x0 + 2 && x < d.x0 + (nx - 1) * c - 2 && y < d.y1 - 2 && y > d.y1 - (ny - 1) * c + 2;
      const V = (x, y, lift = 0) => new THREE.Vector3(x, ground(x, y) * EX + lift, -y);   // x right, -z down the hole, y up (metres)
      const geo = new THREE.PlaneGeometry((nx - 1) * c, (ny - 1) * c, nx - 1, ny - 1); geo.rotateX(-Math.PI / 2);
      const pos = geo.attributes.position; for (let k = 0; k < pos.count; k++) pos.setY(k, g8[k] * d.gs * EX);
      geo.translate(d.x0 + (nx - 1) * c / 2, 0, -(d.y1 - (ny - 1) * c / 2)); geo.computeVertexNormals();
      const t = tex(`h3d/hole${n}.webp`); scene.add(new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: t })));
      // trees: one rounded crown per lidar cell that has something tall on it
      const cells = []; for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) { const hh = h8[j * nx + i] * d.hs; if (hh > 2.5 && ((i + j) % 2 === 0)) cells.push([i, j, hh]); }
      const trees = new THREE.InstancedMesh(new THREE.IcosahedronGeometry(1, 1), new THREE.MeshLambertMaterial({ flatShading: true }), cells.length);
      const m4 = new THREE.Matrix4(), col = new THREE.Color(); let sd = 7;
      const rnd = () => (sd = (sd * 16807) % 2147483647) / 2147483647;
      cells.forEach(([i, j, hh], k) => { const x = d.x0 + i * c + (rnd() - .5) * 1.6, y = d.y1 - j * c + (rnd() - .5) * 1.6, H = hh * EX, rad = 2.6 + rnd() * 1.4;
        m4.compose(new THREE.Vector3(x, ground(x, y) * EX + H * .58, -y), new THREE.Quaternion(), new THREE.Vector3(rad, H * .46, rad)); trees.setMatrixAt(k, m4);
        const v = .30 + rnd() * .12; trees.setColorAt(k, col.setRGB(v * 1.05, v * .95, v * .72)); });
      scene.add(trees);
      // yardage rings laid on the ground, measured from the middle of the green
      const rings = new THREE.Group(); scene.add(rings);
      [100, 150, 200, 250].forEach(yd => { if (yd > d.yd - 20) return; const R = yd * YD; let run = [], lab = null;
        const flush = () => { if (run.length > 2) rings.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(run), new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: .9 }))); run = []; };
        for (let k = 0; k <= 240; k++) { const a = k / 240 * Math.PI * 2, x = d.green[0] + Math.cos(a) * R, y = d.green[1] + Math.sin(a) * R;
          if (inside(x, y)) { run.push(V(x, y, 1)); if (!lab && Math.sin(a) < -.55 && Math.cos(a) < -.15) lab = [x, y]; } else flush(); }
        flush(); if (lab) { const s = label(String(yd), 9); s.position.copy(V(lab[0], lab[1], 7)); rings.add(s); } });
      const tee = V(0, 0), pin = V(d.green[0], d.green[1]); flagAt(scene, pin, 9);
      const teeBox = new THREE.Mesh(new THREE.BoxGeometry(5, .5, 3), new THREE.MeshBasicMaterial({ color: 0x1F4E9D })); teeBox.position.copy(tee).y += .3; scene.add(teeBox);
      const oc = new THREE.OrbitControls(cam, r.domElement); oc.maxPolarAngle = 1.46; oc.minDistance = 25; oc.maxDistance = 1000; oc.screenSpacePanning = false;
      const mid = V(d.green[0] / 2, d.len / 2);
      const cams = { tee: () => { cam.position.copy(V(-4, -95)).setY(tee.y + 62); oc.target.copy(V(d.green[0] * .5, d.len * .5)); },
        top: () => { cam.position.set(mid.x, mid.y + d.len * 1.3, mid.z + 1); oc.target.copy(mid); },
        green: () => { cam.position.copy(V(d.green[0] + 6, d.len + 75)).setY(pin.y + 42); oc.target.copy(V(d.green[0] * .5, d.len * .5)); } };
      el.querySelectorAll('[data-c]').forEach(b => b.onclick = () => { cams[b.dataset.c](); el.querySelectorAll('[data-c]').forEach(x => x.classList.toggle('on', x === b)); });
      cams.tee();
      const lay = () => { rings.visible = show.rings; trees.visible = show.trees; el.querySelectorAll('[data-l]').forEach(b => b.classList.toggle('on', show[b.dataset.l])); };
      el.querySelectorAll('[data-l]').forEach(b => b.onclick = () => { show[b.dataset.l] = !show[b.dataset.l]; lay(); }); lay();
      // the tee shot
      const shot = new THREE.Group(); scene.add(shot); let curve = null, tt = 0;
      const ball = new THREE.Mesh(new THREE.SphereGeometry(1.5, 16, 16), new THREE.MeshBasicMaterial({ color: 0xffffff })); scene.add(ball);
      const carry = (typeof CADDY !== 'undefined') ? CADDY : {};
      const fitClub = yd => { let best = ''; for (const k of Object.keys(carry)) if (carry[k].c && carry[k].c[0] >= yd) best = k; return best; };
      const bar = q('[data-r="clubs"]');
      function pick(i) {
        clubIdx = i; const cl = d.clubs[i], [lx, ly] = cl.at; tt = 0;
        while (shot.children.length) { const o = shot.children.pop(); o.geometry && o.geometry.dispose(); }
        const land = V(lx, ly), dist = Math.hypot(lx, ly);
        const midp = tee.clone().lerp(land, .52); midp.y = Math.max(tee.y, land.y) + dist * .2; midp.x -= dist * .03;
        curve = new THREE.QuadraticBezierCurve3(tee.clone().setY(tee.y + 1), midp, land.clone().setY(land.y + 1));
        shot.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 60, .7, 6), new THREE.MeshBasicMaterial({ color: 0x6FB7F2 })));
        const rw = cl.yd * YD * .10, rd = cl.yd * YD * .06, ang = Math.atan2(lx, ly), ring = [];
        for (let k = 0; k < 48; k++) { const a = k / 48 * Math.PI * 2, ex = Math.cos(a) * rw, ey = Math.sin(a) * rd; ring.push(V(lx + ex * Math.cos(ang) + ey * Math.sin(ang), ly - ex * Math.sin(ang) + ey * Math.cos(ang), 1.2)); }
        shot.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(ring, true), 96, .55, 5, true), new THREE.MeshBasicMaterial({ color: 0xffffff })));
        const inl = []; for (let k = 0; k <= 30; k++) { const u = k / 30; inl.push(V(lx + (d.green[0] - lx) * u, ly + (d.green[1] - ly) * u, 1.2)); }
        shot.add(new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(inl), 60, .35, 5), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: .85 })));
        const s = label(`${cl.club} ${cl.yd}`, 10); s.position.copy(V(lx, ly, 12)); shot.add(s);
        const left = d.yd - cl.yd, short = left > 0, dz1 = (ground(lx, ly) - ground(0, 0)) * FT, dz2 = (ground(d.green[0], d.green[1]) - ground(lx, ly)) * FT;
        const w = v => Math.abs(v) < 2 ? 'level' : `${Math.abs(v).toFixed(0)} ft ${v > 0 ? 'up' : 'down'}`, fc = left <= 275 ? fitClub(left) : '';
        q('[data-r="a"]').textContent = d.par === 3 ? `${cl.club} ${cl.yd}  \u2192  ${Math.abs(left) < 4 ? 'pin high' : Math.abs(left) + ' yd ' + (short ? 'short' : 'long')}` : `${cl.club} ${cl.yd}  →  ${left} in` + (fc ? `  ·  ${fc}` : '');
        q('[data-r="b"]').textContent = d.par === 3 ? `Green is ${w((ground(d.green[0], d.green[1]) - ground(0, 0)) * FT)} from the tee` : `Tee shot ${w(dz1)}  ·  shot in ${w(dz2)}`;
        [...bar.children].forEach((x, k) => x.classList.toggle('on', k === i));
      }
      if (d.par === 3) {   // par 3: the three clubs whose carry sits closest to the hole yardage, flown on the pin line
        const all = Object.keys(carry).filter(k => carry[k].c).map(k => ({ club: k, yd: carry[k].c[0] })).sort((p, q2) => Math.abs(p.yd - d.yd) - Math.abs(q2.yd - d.yd)).slice(0, 3).sort((p, q2) => q2.yd - p.yd);
        const gl = Math.hypot(d.green[0], d.green[1]); d.clubs = all.map(o => ({ club: o.club, yd: o.yd, at: [d.green[0] / gl * o.yd * YD, d.green[1] / gl * o.yd * YD] }));
      }
      d.clubs.forEach((cl, i) => { const b = document.createElement('button'); b.type = 'button'; b.className = 't3-pill'; b.textContent = `${cl.club} ${cl.yd}`; b.onclick = () => pick(i); bar.appendChild(b); });
      pick(Math.min(clubIdx, d.clubs.length - 1));
      r.setAnimationLoop(() => { if (!el.isConnected) return; fit(); tt = calm ? 1 : Math.min(1, tt + .012); ball.position.copy(curve.getPoint(1 - Math.pow(1 - tt, 2.2))); oc.update(); r.render(scene, cam); });
      kill = () => { r.setAnimationLoop(null); r.dispose(); geo.dispose(); t.dispose(); r.forceContextLoss && r.forceContextLoss(); };
    }).catch(e => { console.error('trial3d hole', e); q('.t3-chip').textContent = '3D hole did not load'; });
    return { el, update() {}, dispose() { alive = false; kill(); } };
  }

  /* ------------------------------ 3D green, driven by the tracker's own pin and ball ------------------------------ */
  function makeGreen(n) {
    const EX = 3, el = document.createElement('div'), zd = zdata(n);
    el.innerHTML = `<div class="t3-frame t3-green"><div class="t3-chip"></div></div>`;
    const box = el.firstChild, chip = el.querySelector('.t3-chip');
    const { r, scene, cam, fit } = stage(box);
    const N = zd.n, S = 8 / zd.wft, w = 8, dd = zd.hft * S;
    const geo = new THREE.PlaneGeometry(w, dd, N - 1, N - 1); geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position; for (let k = 0; k < pos.count; k++) pos.setY(k, zd.a[k] * zd.zs * S * EX); geo.computeVertexNormals();
    const t = tex(BOOK[n].green); scene.add(new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ map: t })));
    const V = (x, y, lift = 0) => new THREE.Vector3(x * w - w / 2, (zAt(zd, x, y) - zd.z0) * S * EX + lift, y * dd - dd / 2);
    cam.fov = 38; cam.near = .1; cam.far = 100; cam.position.set(0, 4.6, dd / 2 + 4.2);
    const oc = new THREE.OrbitControls(cam, r.domElement); oc.enablePan = false; oc.minDistance = 2.5; oc.maxDistance = 16; oc.maxPolarAngle = 1.45;
    const dyn = new THREE.Group(); scene.add(dyn);
    const ball = new THREE.Mesh(new THREE.SphereGeometry(.07, 20, 20), new THREE.MeshBasicMaterial({ color: 0xffffff })); ball.visible = false; scene.add(ball);
    let path = null, tt = 0, sig = '';
    function update() {
      const p = X.pins[n], b = X.balls[n], g = (p && b) ? puttGeom(n) : null;
      const read = document.querySelector('.book .prout'), txt = read ? read.textContent : '';
      const s = JSON.stringify([p, b, txt]); if (s === sig) return; sig = s;
      while (dyn.children.length) { const o = dyn.children.pop(); o.traverse && o.traverse(x => x.geometry && x.geometry.dispose()); }
      path = null; ball.visible = false;
      chip.textContent = !p ? 'Tap the map below to drop the pin' : !b ? 'Now tap where you are putting from' : (g ? `${Math.round(g.dist)} ft · ${g.cross.toFixed(1)}% break, high side ${g.high}` : '');
      if (!p) { oc.target.set(0, 0, 0); return; }
      const pinP = V(p.x, p.y); const grp = new THREE.Group(); dyn.add(grp); flagAt(grp, pinP, 1.1); oc.target.copy(pinP);
      if (!b) return;
      const ballP = V(b.x, b.y); oc.target.copy(pinP.clone().lerp(ballP, .4));
      const back = ballP.clone().sub(pinP).setY(0).normalize(); cam.position.copy(ballP).add(back.multiplyScalar(4.4)).setY(ballP.y + 3.4);
      // aim from the tracker's own chart read, so the two always agree
      const m = txt.match(/(?:Aim|Play it)\s+(?:(\d+)')?\s*(?:([\d.]+)")?/), inside = /inside/.test(txt), inches = !m ? 0 : inside ? 1 : (parseFloat(m[1] || 0) * 12 + parseFloat(m[2] || 0)), sgn = g && g.high === 'right' ? 1 : -1;
      const ux = (p.x - b.x) * zd.wft, uy = (p.y - b.y) * zd.hft, L = Math.hypot(ux, uy) || 1, off = sgn * inches / 12;
      const ax = p.x + (-uy / L) * off / zd.wft, ay = p.y + (ux / L) * off / zd.hft;
      const pts = []; for (let k = 0; k <= 40; k++) { const u = k / 40, cx = b.x + (ax - b.x) * .62, cy = b.y + (ay - b.y) * .62;
        const x = (1 - u) * (1 - u) * b.x + 2 * (1 - u) * u * cx + u * u * p.x, y = (1 - u) * (1 - u) * b.y + 2 * (1 - u) * u * cy + u * u * p.y; pts.push(V(x, y, .035)); }
      path = new THREE.CatmullRomCurve3(pts); tt = 0; ball.visible = true;
      dyn.add(new THREE.Mesh(new THREE.TubeGeometry(path, 100, .022, 6), new THREE.MeshBasicMaterial({ color: 0xffffff })));
      const dash = new THREE.Line(new THREE.BufferGeometry().setFromPoints([V(b.x, b.y, .04), V(ax, ay, .04)]), new THREE.LineDashedMaterial({ color: 0xffffff, dashSize: .12, gapSize: .1 })); dash.computeLineDistances(); dyn.add(dash);
      const aimDot = new THREE.Mesh(new THREE.SphereGeometry(.05, 12, 12), new THREE.MeshBasicMaterial({ color: 0x0C2340 })); aimDot.position.copy(V(ax, ay, .05)); dyn.add(aimDot);
    }
    r.setAnimationLoop(() => { if (!el.isConnected) return; fit(); if (path) { tt = calm ? 1 : (tt + .008) % 1.35; ball.position.copy(path.getPoint(Math.min(1, tt))).y += .05; } oc.update(); r.render(scene, cam); });
    return { el, update, dispose() { r.setAnimationLoop(null); r.dispose(); geo.dispose(); t.dispose(); r.forceContextLoss && r.forceContextLoss(); } };
  }

  /* ------------------------------ mount after every tracker render ------------------------------ */
  let cur = null, key = '';
  function mount() {
    const st = document.getElementById('savestat'); if (st) { st.textContent = 'Trial page · nothing saves'; st.classList.remove('live'); }
    const book = document.querySelector('#main .book'), body = book && book.querySelector('.bookbody');
    const tab = X.tab, bookView = X.bookView, hole = X.hole;
    const want = (book && tab === 'hole' && (bookView === 'hole' || (bookView === 'green' && zdata(hole)))) ? bookView + ':' + hole : '';
    if (want !== key) { if (cur) cur.dispose(); cur = null; key = want; if (want) cur = bookView === 'hole' ? makeHole(hole) : makeGreen(hole); }
    if (book) book.classList.toggle('t3on', !!want && bookView === 'hole');
    if (!cur || !body) return;
    if (bookView === 'hole') { if (cur.el.parentNode !== book) { body.style.display = 'none'; book.appendChild(cur.el); } }
    else if (cur.el.parentNode !== body) body.insertBefore(cur.el, body.firstChild);
    cur.update();
  }
  window.__t3 = mount;
  X.rerender();
})();
