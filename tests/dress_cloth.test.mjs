// 옷·머리 흔들림 시험 (node tests/dress_cloth.test.mjs) — web/dressroom/cloth.js
import assert from 'node:assert/strict';
import * as THREE from '../web/dressroom/vendor/three.module.min.js';
import { Rig } from '../web/dressroom/viewer.js';
import { ClothSet, ClothTeam, curve, STEP } from '../web/dressroom/cloth.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };
const near = (a, b, eps, msg) => assert.ok(Math.abs(a - b) <= eps, `${msg}: ${a} vs ${b}`);

/** 뼈대 루트 밑 _Hip(고정) 에서 +x 로 뻗은 사슬 a→b→c (0.1 m 씩). */
function makeRig() {
  const rig = new Rig();
  const S = [1, 1, 1], R = [0, 0, 0, 1];
  rig.add([
    { path: '_Hip', t: [0, 1, 0], r: R, s: S },
    { path: '_Hip/a', t: [0, 0, 0], r: R, s: S },
    { path: '_Hip/a/b', t: [0.1, 0, 0], r: R, s: S },
    { path: '_Hip/a/b/c', t: [0.1, 0, 0], r: R, s: S },
    { path: '_Hip/a/b/c/d', t: [0.1, 0, 0], r: R, s: S },
  ]);
  return rig;
}

function team(params = {}, extra = {}) {
  const verts = ['_Hip/a', '_Hip/a/b', '_Hip/a/b/c', '_Hip/a/b/c/d'];
  const struct = [], root = [], comp = [];
  for (let i = 1; i < 4; i++) {
    struct.push(i, i - 1, 0.1);
    if (i < 3) struct.push(i, i + 1, 0.1);
    root.push(i, 0, 0.1 * i);
    comp.push(i, i - 1, 1, 0, 0, 0, 0, 0, 1);
  }
  return {
    name: '시험', verts, sel: [2, 1, 1, 1], depth: [0, 1 / 3, 2 / 3, 1], parent: [-1, 0, 1, 2],
    params: { algorithm: 1, useGravity: 1, gravity: [-9.8, 0, 0, 0, 0], gravityDirection: [0, 1, 0], useDrag: 1, drag: [0.02, 0, 0, 0, 0],
      structDistanceStiffness: [1, 0, 0, 0, 0], mass: [1, 0, 0, 0, 0], radius: [0.01, 0, 0, 0, 0], ...params },
    struct, root, comp, bend: [], pen: [], colliders: [], ...extra,
  };
}

/** 프레임 돌리기 — 매 프레임 기본 자세로 돌린 뒤(rig.rest) 흔들림. */
function run(rig, set, models, secs, dt = 1 / 60, each = null) {
  for (let k = 0; k < Math.round(secs / dt); k++) {
    rig.rest(true);
    if (each) each(k);
    set.update(dt, rig, models);
  }
  rig.root.updateMatrixWorld(true);
}

const world = (rig, p) => new THREE.Vector3().setFromMatrixPosition(rig.bones.get(p).matrixWorld);
/** 뼈대 루트 기준 위치 (Rig 루트는 x 를 뒤집는다). */
const model = (rig, p) => rig.root.worldToLocal(world(rig, p));

t('설정 곡선', () => {
  assert.equal(curve(3, 0.5), 3);
  assert.equal(curve([1, 5, 0, 0, 0], 0.7), 1);          // 끝 안 씀
  near(curve([0, 10, 1, 0, 0], 0.25), 2.5, 1e-9, '직선');
  assert.ok(curve([0, 10, 1, 0.8, 1], 0.25) > 2.5);     // 곡선 + → 앞에서 빨리
  assert.ok(curve([0, 10, 1, -0.8, 1], 0.25) < 2.5);
  near(curve([0, 10, 1, 0.5, 1], 1), 10, 1e-9, '끝');
});

t('중력으로 처지고 길이는 유지, 쉬면 기본 자세로', () => {
  const rig = makeRig(), set = new ClothSet();
  const m = { meta: { cloth: [team()] } };
  run(rig, set, [m], 2);
  const tip = world(rig, '_Hip/a/b/c/d');
  assert.ok(tip.y < 1 - 0.2, `끝이 처진다 ${tip.y}`);
  for (const [a, b] of [['_Hip/a', '_Hip/a/b'], ['_Hip/a/b', '_Hip/a/b/c'], ['_Hip/a/b/c', '_Hip/a/b/c/d']])
    near(world(rig, a).distanceTo(world(rig, b)), 0.1, 0.012, `${b} 길이`);
  // 다음 프레임 pose 의 rig.rest 로 기본 자세
  rig.rest(true);
  near(world(rig, '_Hip/a/b/c/d').y, 1, 1e-9, '쉼 자세');
  assert.equal(set.teamsOf(m).length, 1);
});

t('뼈가 자식 쪽을 가리킨다', () => {
  const rig = makeRig(), set = new ClothSet();
  run(rig, set, [{ meta: { cloth: [team()] } }], 2);
  const b = rig.bones.get('_Hip/a/b');
  const dir = new THREE.Vector3(1, 0, 0).transformDirection(b.matrixWorld);
  const want = world(rig, '_Hip/a/b/c').sub(world(rig, '_Hip/a/b')).normalize();
  assert.ok(dir.dot(want) > 0.99, `b 의 +x 가 c 쪽 ${dir.dot(want)}`);
});

t('회전 제한 각 안에서만 처진다', () => {
  const rig = makeRig(), set = new ClothSet();
  run(rig, set, [{ meta: { cloth: [team({ useClampRotation: 1, clampRotationAngle2: [10, 0, 0, 0, 0] })] } }], 2);
  const a = model(rig, '_Hip/a'), b = model(rig, '_Hip/a/b');
  const ang = new THREE.Vector3().subVectors(b, a).angleTo(new THREE.Vector3(1, 0, 0)) / (Math.PI / 180);
  assert.ok(ang < 14, `첫 마디 ${ang}°`);
});

t('부딪힘 공 밖에 머문다', () => {
  const rig = makeRig(), set = new ClothSet();
  const col = { bone: '_Hip', t: [0, 0, 0], r: [0, 0, 0, 1], s: [1, 1, 1], kind: 'sphere', center: [0.25, -0.12, 0], axis: 0, length: 0, r0: 0.08, r1: 0.08 };
  run(rig, set, [{ meta: { cloth: [team({ useCollision: 1 }, { colliders: [col] })] } }], 2);
  const c = new THREE.Vector3(0.25, 1 - 0.12, 0);
  for (const p of ['_Hip/a/b', '_Hip/a/b/c', '_Hip/a/b/c/d'])
    assert.ok(model(rig, p).distanceTo(c) >= 0.08 + 0.01 - 2e-3, `${p} 가 공 밖 ${model(rig, p).distanceTo(c)}`);
});

t('뿌리를 안 뒤집거나 돌려도 아래로 처진다', () => {
  const rig = makeRig(), set = new ClothSet();
  rig.root.scale.x = 1;            // Rig 는 원래 x 뒤집기 — 안 뒤집은 것도 본다
  rig.root.rotation.y = 1.2;
  run(rig, set, [{ meta: { cloth: [team()] } }], 2);
  const tip = world(rig, '_Hip/a/b/c/d');
  assert.ok(tip.y < 1 - 0.2, `끝이 처진다 ${tip.y}`);
  near(world(rig, '_Hip/a/b/c').distanceTo(tip), 0.1, 0.012, '길이');
});

t('뿌리가 옮겨지면 뒤처져 흔들린다 (월드 기준)', () => {
  const rig = makeRig(), set = new ClothSet();
  const m = { meta: { cloth: [team({ gravity: [0, 0, 0, 0, 0], useRestoreRotation: 1, restoreRotation2: [0.05, 0, 0, 0, 0] })] } };
  run(rig, set, [m], 0.5);
  rig.root.position.z = 0.05;   // 한 프레임에 5cm (3 m/s 상한 안)
  rig.rest(true);
  set.update(1 / 60, rig, [m]);
  rig.root.updateMatrixWorld(true);
  const tip = world(rig, '_Hip/a/b/c/d');
  assert.ok(tip.z < 0.045, `끝이 뒤에 남는다 ${tip.z}`);
  run(rig, set, [m], 3);
  near(world(rig, '_Hip/a/b/c/d').z, 0.05, 0.02, '다시 따라온다');
});

t('크게 순간 이동하면 처음부터 (튀지 않게)', () => {
  const rig = makeRig(), set = new ClothSet();
  const m = { meta: { cloth: [team()] } };
  run(rig, set, [m], 1);
  rig.root.position.x = 5;
  rig.rest(true);
  set.update(1 / 60, rig, [m]);
  rig.root.updateMatrixWorld(true);
  near(model(rig, '_Hip/a/b/c/d').x, 0.3, 0.02, '기본 자세에서 다시');
  near(model(rig, '_Hip/a/b/c/d').y, 1, 0.02, '기본 자세에서 다시 (y)');
});

t('없는 뼈가 있는 팀은 안 돌고, 바깥 팀은 더하고 뺀다', () => {
  const rig = makeRig(), set = new ClothSet();
  const bad = team();
  bad.verts = ['_Hip/a', '_Hip/x', '_Hip/y', '_Hip/z'];
  assert.equal(new ClothTeam(bad, rig).ok, false);
  const ext = set.add(team(), rig);
  assert.equal(set.update(1 / 60, rig, []), 1);
  set.remove(ext);
  assert.equal(set.update(1 / 60, rig, []), 0);
  assert.ok(STEP > 0);
});

t('굽힘 구속이 있는 두 줄 천도 흩어지지 않고 판판함을 지킨다', () => {
  // 나란한 두 사슬 a0→a1→a2, b0→b1→b2 (0.1 m 씩, 사이 0.1 m) — 뿌리 둘 고정, 삼각형 넷
  const rig = new Rig();
  const S = [1, 1, 1], R = [0, 0, 0, 1];
  rig.add([
    { path: '_Hip', t: [0, 1, 0], r: R, s: S },
    { path: '_Hip/a0', t: [0, 0, 0], r: R, s: S },
    { path: '_Hip/a0/a1', t: [0.1, 0, 0], r: R, s: S },
    { path: '_Hip/a0/a1/a2', t: [0.1, 0, 0], r: R, s: S },
    { path: '_Hip/b0', t: [0, 0, 0.1], r: R, s: S },
    { path: '_Hip/b0/b1', t: [0.1, 0, 0], r: R, s: S },
    { path: '_Hip/b0/b1/b2', t: [0.1, 0, 0], r: R, s: S },
  ]);
  const verts = ['_Hip/a0', '_Hip/a0/a1', '_Hip/a0/a1/a2', '_Hip/b0', '_Hip/b0/b1', '_Hip/b0/b1/b2'];
  const P = [[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0], [0, 0, 0.1], [0.1, 0, 0.1], [0.2, 0, 0.1]].map((v) => new THREE.Vector3(...v));
  const struct = [];
  for (const [i, j] of [[0, 1], [1, 2], [3, 4], [4, 5], [1, 4], [2, 5], [0, 4], [1, 5]]) {
    const L = P[i].distanceTo(P[j]);
    struct.push(i, j, L, j, i, L);
  }
  const data = {
    name: '두 줄', verts, sel: [2, 1, 1, 2, 1, 1], depth: [0, 0.5, 1, 0, 0.5, 1], parent: [-1, 0, 1, -1, 3, 4],
    params: { algorithm: 1, useGravity: 1, gravity: [-9.8, 0, 0, 0, 0], gravityDirection: [0, 1, 0], useDrag: 1, drag: [0.02, 0, 0, 0, 0],
      structDistanceStiffness: [1, 0, 0, 0, 0], mass: [1, 0, 0, 0, 0], radius: [0.01, 0, 0, 0, 0], useTriangleBend: 1, triangleBend2: [1, 0, 0, 0, 0] },
    struct, root: [1, 0, 0.1, 2, 0, 0.2, 4, 3, 0.1, 5, 3, 0.2],
    comp: [1, 0, 1, 0, 0, 0, 0, 0, 1, 2, 1, 1, 0, 0, 0, 0, 0, 1, 4, 3, 1, 0, 0, 0, 0, 0, 1, 5, 4, 1, 0, 0, 0, 0, 0, 1],
    // [날개0, 날개1, 모서리0, 모서리1, 쉼 각, 방향] — 삼각형 (0,1,4)(0,4,3)·(1,2,5)(1,5,4)·(0,1,4)(1,5,4)
    bend: [1, 3, 0, 4, 0, 0, 2, 4, 1, 5, 0, 0, 0, 5, 1, 4, 0, 0],
    pen: [], colliders: [],
  };
  const set = new ClothSet();
  const m = { meta: { cloth: [data] } };
  // 한쪽 끝만 한 번 세게 밀어도 (굽힘이 이웃끼리 키워 가면 여기서 튄다)
  run(rig, set, [m], 0.2);
  set.teamsOf(m)[0].pos[5].y += 0.05;
  run(rig, set, [m], 3);
  const team = set.teamsOf(m)[0];
  for (const p of team.pos) assert.ok(Number.isFinite(p.x + p.y + p.z), '수가 아님');
  near(team.pos[1].distanceTo(team.pos[2]), 0.1, 0.015, 'a 끝 길이');
  near(team.pos[4].distanceTo(team.pos[5]), 0.1, 0.015, 'b 끝 길이');
  assert.ok(team.pos[2].y < 1 - 0.05, `처진다 ${team.pos[2].y}`);   // 모델 좌표 (_Hip 이 y 1)
  // 두 사슬이 같이 처져 천이 접히지 않는다 (끝 높이 차가 작다)
  assert.ok(Math.abs(team.pos[2].y - team.pos[5].y) < 0.03, `판판함 ${team.pos[2].y} vs ${team.pos[5].y}`);
});

console.log(`${n}개 통과`);
