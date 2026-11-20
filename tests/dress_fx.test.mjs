// 드레스룸 의상 이펙트 시험 (node tests/dress_fx.test.mjs) — web/dressroom/fx.js 를 화면 없이 돌린다
import assert from 'node:assert/strict';
import * as THREE from '../web/dressroom/vendor/three.module.min.js';
import { curve, color, rng, FxPlayer } from '../web/dressroom/fx.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };
const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const line = Array.from({ length: 17 }, (_, i) => i / 16);
const I16 = new THREE.Matrix4().toArray();

function system(o = {}) {
  return {
    name: 's', dur: 1, loop: true, prewarm: false, delay: 0, space: 0, scaling: 0, life: 0.5, speed: 1, size: 0.1, rot: 0,
    flipRot: 0, color: [1, 1, 1, 1], gravity: 0, max: 100, emit: { rate: 20, dist: 0, bursts: [] }, streams: [],
    render: { mode: 0, align: 0, len: 2, vscale: 0, max: 0.5, min: 0, pivot: [0, 0, 0], flip: [0, 0], sort: 0 },
    m: I16, mat: { name: 'm', kind: 'dissolve', blend: [5, 10], cull: 0, f: {}, c: {}, t: {} }, ...o,
  };
}

function fx(systems, track = {}, meshes = []) {
  return { tracks: [{ fx: 0, bone: '_Head', rbone: '_Head', off: [0, 0, 0], rot: [0, 0, 0, 1], turn: true, hood: false, ...track }],
    overlays: [], prefabs: [{ name: 'p', systems, meshes }] };
}

function rig() {
  const root = new THREE.Group();
  root.scale.x = -1;   // 드레스룸 뼈대 루트처럼 x 를 뒤집는다
  const bones = { _Head: new THREE.Bone() };
  bones._Head.position.set(0, 1.5, 0);
  root.add(bones._Head);
  root.updateMatrixWorld(true);
  return { root, bones, find: (name) => bones[name] || null };
}

const model = (o = {}) => ({ id: 'X', group: new THREE.Group(), meshes: [], shown: true, hood: 'off', ...o });
const camera = new THREE.PerspectiveCamera(30, 1, 0.05, 50);
camera.position.set(0, 1.5, 3);
camera.lookAt(0, 1.5, 0);
camera.updateMatrixWorld();
const tex = () => null;

function run(p, r, sec, dt = 1 / 30) {
  for (let k = 0; k < Math.round(sec / dt); k++) p.update(dt, r, camera);
}
const sys0 = (p) => p.tracks[0].systems[0];
const drawn = (s) => s.geometry.drawRange.count;

t('곡선 값', () => {
  assert.equal(curve(2, 0.3), 2);
  assert.equal(curve(undefined, 0.3), 0);
  close(curve([1, 3], 0, 0.5), 2);
  close(curve({ c: line }, 0.5), 0.5);
  close(curve({ c: line }, 2), 1);                                   // 범위 밖은 끝 값
  close(curve({ c: line, c2: line.map(() => 0) }, 1, 0.25), 0.25);   // 두 곡선 사이
});

t('색 값', () => {
  const out = [0, 0, 0, 0];
  assert.deepEqual(color(null, 0, 0, out), [1, 1, 1, 1]);
  assert.deepEqual(color({ c: [[0, 0, 0, 0], [1, 1, 1, 1]] }, 0, 0.5, out), [0.5, 0.5, 0.5, 0.5]);
  const g = line.map((v) => [v, 0, 0, 1]);
  close(color({ g }, 0.75, 0, out)[0], 0.75);
  close(color({ r: g }, 0, 0.25, out)[0], 0.25);                    // 그라디언트 안에서 아무 색
});

t('무작위는 시드가 같으면 같다', () => {
  const a = rng(7), b = rng(7), c = rng(8);
  const xs = [a(), a(), a()];
  assert.deepEqual(xs, [b(), b(), b()]);
  assert.notDeepEqual(xs, [c(), c(), c()]);
  assert.ok(xs.every((x) => x >= 0 && x < 1));
});

t('초당 방출 — 뼈 자리에서 나와 앞(+z)으로', () => {
  const r = rig(), m = model();
  const p = new FxPlayer(fx([system()]), m, tex);
  assert.equal(p.group.parent, m.group);
  run(p, r, 2);
  const s = sys0(p);
  assert.ok(s.parts.length >= 8 && s.parts.length <= 12, `입자 ${s.parts.length}`);
  assert.equal(drawn(s), s.parts.length * 6);
  const pos = s.geometry.attributes.position.array;
  for (let i = 0; i < s.parts.length * 4; i++) {
    const [x, y, z] = [pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]];
    assert.ok(Number.isFinite(x + y + z));
    assert.ok(Math.abs(x) < 0.2 && Math.abs(y - 1.5) < 0.2 && z > -0.1 && z < 0.6, `${x},${y},${z}`);
  }
  p.dispose();
  assert.equal(p.group.parent, null);
});

t('소켓 뼈가 없으면 안 그리다가 생기면 붙는다', () => {
  const r = rig(), m = model();
  const p = new FxPlayer(fx([system()], { bone: 'EffectSocket_Helmet_01', rbone: 'EffectSocket_Helmet_01' }), m, tex);
  run(p, r, 0.5);
  assert.equal(drawn(sys0(p)), 0);
  const b = new THREE.Bone();
  r.root.add(b);
  r.bones.EffectSocket_Helmet_01 = b;   // 다른 옷이 소켓을 가져왔다
  run(p, r, 1.5);
  assert.ok(sys0(p).parts.length > 0);
});

t('후드 트랙은 후드를 쓴 때만, 가려진 옷은 안 그린다', () => {
  const r = rig(), m = model();
  const p = new FxPlayer(fx([system()], { hood: true }), m, tex);
  run(p, r, 1);
  assert.equal(drawn(sys0(p)), 0);
  m.hood = 'on';
  run(p, r, 1);
  assert.ok(drawn(sys0(p)) > 0);
  m.shown = false;
  run(p, r, 0.1);
  assert.equal(drawn(sys0(p)), 0);
});

t('반복하지 않는 시스템은 끝나면 다시 튼다', () => {
  const r = rig();
  const one = system({ loop: false, dur: 0.5, life: 0.2, emit: { rate: 0, dist: 0, bursts: [[0, 1, 1, 0.01, 1]] } });
  const p = new FxPlayer(fx([one]), model(), tex);
  run(p, r, 0.1);
  assert.equal(sys0(p).parts.length, 1);
  run(p, r, 0.25);
  assert.equal(sys0(p).parts.length, 0);
  run(p, r, 0.3);   // 0.5 초가 지나 처음부터
  assert.equal(sys0(p).parts.length, 1);
});

t('보통 메시는 입자 하나로 늘 떠 있다', () => {
  const r = rig();
  const still = system({ life: 1e9, speed: 0, size: 1, max: 1, emit: { rate: 0, dist: 0, bursts: [[0, 1, 1, 0.01, 1]] },
    render: { mode: 4, align: 2, len: 1, vscale: 0, max: 0, min: 0, pivot: [0, 0, 0], flip: [0, 0], sort: 0 }, mesh: 0 });
  const p = new FxPlayer(fx([still], {}, ['quad']), model(), tex);
  run(p, r, 3);
  const s = sys0(p);
  assert.equal(s.parts.length, 1);
  assert.equal(drawn(s), 6);   // 사각형 메시 하나
  assert.equal(s.material.side, THREE.DoubleSide);
});

t('정점 흐름 — 사용자 값이 UV 뒤 칸에 차례로', () => {
  const r = rig();
  const s0 = system({ streams: [0, 1, 3, 4, 34], custom: [[0.25, 0.5, 0.75, 1], []], emit: { rate: 0, dist: 0, bursts: [[0, 1, 1, 0.01, 1]] } });
  const p = new FxPlayer(fx([s0]), model(), tex);
  run(p, r, 0.1);
  const g = sys0(p).geometry.attributes;
  assert.deepEqual(Array.from(g.tex2.array.slice(0, 2)), [0.25, 0.5]);
  assert.deepEqual(Array.from(g.extra.array.slice(0, 4)), [0.75, 1, 0, 0]);
});

t('AlphaTex 셰이더 — 모양 알파를 _AlphaTex 초록에서 (사용자 값 tcd1.xy 만큼 밀어)', () => {
  const s = system({ mat: { name: 'b', kind: 'alphatex', blend: [5, 10], cull: 0, f: {}, c: {}, t: {} } });
  const m = sys0(new FxPlayer(fx([s]), model(), tex)).material;
  assert.match(m.fragmentShader, /fxSample\(_AlphaTex, [^;]*vExtra\.xy, _AlphaTex_sRGB\)\.g/);
  assert.match(m.fragmentShader, /_Add_Noise_Alpha/);
  close(m.uniforms._Add_Noise_Alpha.value, 0.35);   // 재질에 없으면 셰이더 기본값
  const q = system({ mat: { ...s.mat, f: { _Add_Noise_Alpha: 0.1 } } });
  close(sys0(new FxPlayer(fx([q]), model(), tex)).material.uniforms._Add_Noise_Alpha.value, 0.1);
});

t('메시 파티클의 앞면 — 뒤집힌 축이라 뒷면 버림이면 BackSide', () => {
  const s = system({ render: { mode: 4, align: 2, len: 1, vscale: 0, max: 0, min: 0, pivot: [0, 0, 0], flip: [0, 0], sort: 0 },
    mesh: 0, mat: { name: 'b', kind: 'fresnel', blend: [5, 10], cull: 2, f: {}, c: {}, t: {} } });
  const p = new FxPlayer(fx([s], {}, ['sphere']), model(), tex);
  assert.equal(sys0(p).material.side, THREE.BackSide);
  const q = new FxPlayer(fx([system({ mat: { ...s.mat } })]), model(), tex);
  assert.equal(sys0(q).material.side, THREE.DoubleSide);   // 사각형은 양면
});

console.log(`${n}개 통과`);
