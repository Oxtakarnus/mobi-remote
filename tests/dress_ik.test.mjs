// 드레스룸 손 IK 시험 (node tests/dress_ik.test.mjs) — web/dressroom/ik.js
import assert from 'node:assert/strict';
import * as THREE from '../web/dressroom/vendor/three.module.min.js';
import { solveIk, weight } from '../web/dressroom/ik.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };

/** 거울 루트 밑 팔 하나(어깨 → 위팔 → 아래팔 → 손 → 손바닥 → 소품)와 따로 선 뼈들. */
function arm() {
  const root = new THREE.Group();
  root.scale.x = -1;
  const bones = new Map();
  const bone = (name, parent, x, y, z) => {
    const b = new THREE.Bone();
    b.name = name;
    b.position.set(x, y, z);
    parent.add(b);
    bones.set(name, b);
    return b;
  };
  const sh = bone('Shoulder', root, 0.2, 1.4, 0);
  const up = bone('Upper', sh, 0, 0, 0);
  const fo = bone('Fore', up, 0, -0.3, 0);
  const ha = bone('Hand', fo, 0, -0.25, 0);
  const pa = bone('Palm', ha, 0, -0.05, 0);
  bone('Tool', pa, 0.03, 0, 0.02);
  bone('Mouth', root, 0.05, 1.55, 0.12);
  bone('Cup', root, 0.25, 1.1, 0.25);
  root.updateMatrixWorld(true);
  return { root, find: (name) => bones.get(name) || null };
}

const world = (rig, name) => rig.find(name).getWorldPosition(new THREE.Vector3());

t('무게는 구간 안에서 섞는 시간만큼', () => {
  const k = { begin: 1, end: 3, fin: 0.5, fout: 1 };
  assert.equal(weight(k, 0.9), 0);
  assert.equal(weight(k, 1.25), 0.5);
  assert.equal(weight(k, 1.8), 1);
  assert.equal(weight(k, 2.5), 0.5);
  assert.equal(weight(k, 3), 0);
  assert.equal(weight({ begin: 0, end: 1, fin: 0, fout: 0 }, 0.5), 1);
  assert.equal(weight(k, null), 0);
});

t('disp — 손에 든 소품을 입에', () => {
  const rig = arm();
  solveIk(rig, [{ bone: 'Palm', mode: 'disp', target: 'Tool', dest: 'Mouth', begin: 0, end: 2, fin: 0, fout: 0 }], 1);
  rig.root.updateMatrixWorld(true);
  assert.ok(world(rig, 'Tool').distanceTo(world(rig, 'Mouth')) < 0.005);
  const len = world(rig, 'Upper').distanceTo(world(rig, 'Fore'));
  assert.ok(Math.abs(len - 0.3) < 1e-4);   // 뼈 길이는 그대로
});

t('ref — 손바닥을 다른 뼈에, 무게 반이면 반만', () => {
  const rig = arm();
  const p0 = world(rig, 'Palm');
  const k = { bone: 'Palm', mode: 'ref', target: 'Cup', dest: '', begin: 0, end: 2, fin: 1, fout: 0 };
  solveIk(rig, [k], 0.5);
  rig.root.updateMatrixWorld(true);
  const want = p0.clone().lerp(world(rig, 'Cup'), 0.5);
  assert.ok(world(rig, 'Palm').distanceTo(want) < 0.005);
});

t('구간 밖이면 그대로', () => {
  const rig = arm();
  const p0 = world(rig, 'Palm');
  solveIk(rig, [{ bone: 'Palm', mode: 'ref', target: 'Cup', dest: '', begin: 0, end: 2, fin: 0, fout: 0 }], 2.5);
  assert.ok(world(rig, 'Palm').distanceTo(p0) < 1e-9);
});

t('손에 딸리지 않은 target 은 손바닥을 같은 만큼', () => {
  const rig = arm();
  const p0 = world(rig, 'Palm'), c = world(rig, 'Cup'), mo = world(rig, 'Mouth');
  solveIk(rig, [{ bone: 'Palm', mode: 'disp', target: 'Cup', dest: 'Mouth', begin: 0, end: 2, fin: 0, fout: 0 }], 1);
  rig.root.updateMatrixWorld(true);
  assert.ok(world(rig, 'Palm').distanceTo(p0.add(mo.sub(c))) < 0.005);
  assert.ok(world(rig, 'Cup').distanceTo(c.add(new THREE.Vector3())) < 1e-9);   // 남의 뼈는 안 움직인다
});

console.log(`${n}개 통과`);
