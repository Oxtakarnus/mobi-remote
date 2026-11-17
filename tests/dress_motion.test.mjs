// 드레스룸 동작 탭 시험 (node tests/dress_motion.test.mjs) — web/dressroom/motion.js · anim.js Clip · facial.js
import assert from 'node:assert/strict';
import { Clip, lerpQuat } from '../web/dressroom/anim.js';
import { Motion, MotionTable } from '../web/dressroom/motion.js';
import { FaceKeys, hasMorph } from '../web/dressroom/facial.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };

/** 뼈 하나(위치 x 만 프레임 번호)인 클립 — frames 개, 30fps. */
function clip(frames, path = 'A') {
  const data = new Float32Array(frames * 3);
  for (let i = 0; i < frames; i++) data[i * 3] = i;
  return new Clip({ fps: 30, frames, duration: (frames - 1) / 30, tracks: [{ path, kind: 'p', off: 0, n: frames }] }, data.buffer);
}

function rig(...paths) {
  const bones = new Map(paths.map((p) => [p, { position: { x: -1, set(x) { this.x = x; } } }]));
  return { bones, x: (p = 'A') => bones.get(p).position.x };
}

t('클립 길이와 한 번만 틀기', () => {
  const c = clip(31), r = rig('A');
  assert.equal(c.length, 1);
  c.apply(r, 1.5);
  assert.equal(r.x(), 15);           // 반복 — 한 바퀴 지나 반
  c.apply(r, 1.5, false);
  assert.equal(r.x(), 30);           // 한 번 — 끝 자세에서 멈춘다
  c.apply(r, -1, false);
  assert.equal(r.x(), 0);
});

t('시작 단계는 한 번, 마지막 단계는 반복', () => {
  const r = rig('A', 'B');
  const m = new Motion([{ clip: clip(31), face: null }, { clip: clip(11, 'B'), face: clip(11, 'A') }], true);
  m.apply(r, 0.5);
  assert.equal(r.x('A'), 15);
  assert.equal(r.x('B'), -1);        // 반복 단계는 아직
  m.apply(r, 1 + 0.5);               // 시작 1초 뒤 반복 단계 0.5초 = 한 바퀴(10/30초) 넘어
  assert.equal(Math.round(r.x('B')), 5);
  assert.equal(Math.round(r.x('A')), 5);   // 표정도 같은 시간
  assert.equal(m.picked, true);
});

t('표정 키 — 칸은 섞지 않고 모프는 섞는다, 동작 단계와 같은 시간', () => {
  const keys = { fps: 30, frames: 3, tracks: [
    { o: 'Mesh_EyeBase_L', p: 'MT_BlinkDown_L', t: 'morph', v: [0, 1, 0] },
    { o: 'Mesh_Skin_Head', p: '_EmotionMouthMapAtlasSize.z', t: 'shader', v: [1, 25, 25] },
    { o: 'Mesh_EyeBasePlane', p: 'Visibility', t: 'vis', v: [1] }] };
  const k = new FaceKeys(keys), out = new Map();
  k.sample(0.5 / 30, true, out);
  assert.equal(out.get('morph/MT_BlinkDown_L'), 0.5);
  assert.equal(out.get('Mesh_Skin_Head/_EmotionMouthMapAtlasSize.z'), 1);
  assert.equal(out.get('Mesh_EyeBasePlane/Visibility'), 1);
  assert.ok(hasMorph(out));
  assert.equal(hasMorph(new Map([['Mesh_EyeBall/Visibility', 0]])), false);
  // 클립 meta.face → Clip.keys, Motion.faceKeys 는 apply 와 같은 단계·시간
  const face = clip(3, 'A');
  face.keys = new FaceKeys(keys);
  const m = new Motion([{ clip: clip(31), face: null }, { clip: clip(3, 'B'), face }], true);
  assert.equal(m.faceKeys(0.5, new Map()), false);   // 시작 단계는 표정 짝 없음
  const o2 = new Map();
  assert.equal(m.faceKeys(1 + 1 / 30, o2), true);
  assert.ok(Math.abs(o2.get('morph/MT_BlinkDown_L') - 1) < 1e-9);
  assert.equal(new Clip({ fps: 30, frames: 1, duration: 0, tracks: [], face: keys }, new ArrayBuffer(0)).keys.frames, 3);
});

const TABLE = {
  cats: [{ id: 'common', name: '공통' }, { id: 'emotion', name: '감정 표현' }],
  list: [
    { id: 's:PeaceWalk', cat: 'common', name: '걷기', steps: { Female: { '': ['HF@Walk'], Fat: ['HF@Walk_Fat'] } } },
    { id: 'e:Bye', cat: 'emotion', name: '손인사', steps: { Female: { '': ['HF@Bye_Start', 'HF@Bye_Loop'] }, Male: { '': ['HM@Bye'] } } },
  ],
  facial: { 'HF@Bye_Loop': 'HF@Bye_Loop_Facial' },
};

t('동작 표 — 체형 폴더·갈래·검색', () => {
  const mt = new MotionTable(TABLE);
  assert.equal(mt.ok, true);
  assert.deepEqual(mt.cats(), [['common', '공통'], ['emotion', '감정 표현']]);
  assert.deepEqual(mt.list('common', 'Male').map((e) => e.id), []);
  assert.deepEqual(mt.list(null, 'Female', '인사').map((e) => e.id), ['e:Bye']);
  assert.equal(mt.has('e:Bye', 'Infant'), false);
  assert.equal(new MotionTable(null).ok, false);
});

t('단계 — 셰이프 것이 없으면 기본, 표정 짝', () => {
  const mt = new MotionTable(TABLE);
  assert.deepEqual(mt.steps('s:PeaceWalk', 'Female', 'Fat'), [{ body: 'HF@Walk_Fat', face: null }]);
  assert.deepEqual(mt.steps('s:PeaceWalk', 'Female', 'Thin'), [{ body: 'HF@Walk', face: null }]);
  assert.deepEqual(mt.steps('e:Bye', 'Female', ''), [{ body: 'HF@Bye_Start', face: null }, { body: 'HF@Bye_Loop', face: 'HF@Bye_Loop_Facial' }]);
  assert.equal(mt.steps('e:Bye', 'Infant', ''), null);
});

t('표정 — 얼굴 클립 하나, 몸 동작 단계는 없다', () => {
  const mt = new MotionTable({ ...TABLE, list: [...TABLE.list,
    { id: 'f:Kiss', cat: 'face', name: '😘 키스', steps: { Female: { '': ['HF@FaceOnly_Kiss_Facial'] } } }] });
  assert.equal(mt.isFace('f:Kiss'), true);
  assert.equal(mt.isFace('e:Bye'), false);
  assert.equal(mt.isFace('nope'), false);
  assert.equal(mt.faceStem('f:Kiss', 'Female'), 'HF@FaceOnly_Kiss_Facial');
  assert.equal(mt.faceStem('f:Kiss', 'Male'), null);
  assert.equal(mt.faceStem('e:Bye', 'Female'), null);
  assert.equal(mt.steps('f:Kiss', 'Female', ''), null);   // 몸 동작으로 틀지 않는다
});

t('패션 무기 — 전투 동작(drawn)만 손에, 나머지·고르지 않음은 넣은 모습', () => {
  const mt = new MotionTable({ ...TABLE, list: [...TABLE.list,
    { id: 's:AlertStand', cat: 'common', name: '경계 자세', drawn: true, steps: { Female: { '': ['HF@Alert'] } } }] });
  assert.equal(mt.weapon('s:AlertStand'), 'Drawn');
  assert.equal(mt.weapon(TABLE.list[0].id), 'Undrawn');
  assert.equal(mt.weapon(null), 'Undrawn');
  assert.equal(mt.weapon('없는 것'), 'Undrawn');
});

t('직업별 동작 — 무기 직업 갈래가 이 체형에 있으면 그것, 없으면 기본', () => {
  const mt = new MotionTable({ ...TABLE, list: [...TABLE.list,
    { id: 's:AlertStand', cat: 'common', name: '경계 자세', drawn: true, steps: { Female: { '': ['HF@Alert'] }, Male: { '': ['HM@Alert'] } },
      jobs: { Archer: { Female: { '': ['HF@Archer_Alert'], Fat: ['HF@Archer_Alert_Fat'] } } } }] });
  assert.deepEqual(mt.steps('s:AlertStand', 'Female', '', 'Archer'), [{ body: 'HF@Archer_Alert', face: null }]);
  assert.deepEqual(mt.steps('s:AlertStand', 'Female', 'Fat', 'Archer'), [{ body: 'HF@Archer_Alert_Fat', face: null }]);
  assert.deepEqual(mt.steps('s:AlertStand', 'Male', '', 'Archer'), [{ body: 'HM@Alert', face: null }]);     // 이 체형엔 없다
  assert.deepEqual(mt.steps('s:AlertStand', 'Female', '', 'Mage'), [{ body: 'HF@Alert', face: null }]);     // 없는 직업
  assert.deepEqual(mt.steps('s:AlertStand', 'Female', ''), [{ body: 'HF@Alert', face: null }]);             // 무기 없음
  assert.equal(mt.byJob('s:AlertStand'), true);
  assert.equal(mt.byJob('s:PeaceWalk'), false);
  assert.equal(mt.byJob(null), false);
});

t('회전 보간 — 길이가 1 보다 조금 큰 키도 작은 각을 건너뛰지 않는다', () => {
  const q = () => { const v = { x: 0, y: 0, z: 0, w: 0, set(x, y, z, w) { Object.assign(this, { x, y, z, w }); return this; },
    normalize() { const l = Math.hypot(this.x, this.y, this.z, this.w); this.x /= l; this.y /= l; this.z /= l; this.w /= l; return this; } }; return v; };
  const h = (deg) => (deg * Math.PI) / 360;
  const k = 1.00001;   // 게임 곡선에서 뽑은 키처럼 길이가 조금 크다
  const d = new Float32Array([0, Math.sin(h(0)) * k, 0, Math.cos(h(0)) * k, 0, Math.sin(h(0.1)) * k, 0, Math.cos(h(0.1)) * k]);
  const mid = lerpQuat(q(), d, 0, 4, 0.5);
  const ang = (2 * Math.asin(mid.y) * 180) / Math.PI;
  assert.ok(Math.abs(ang - 0.05) < 0.005, `가운데 ${ang}°`);   // three.js slerp 는 0° (첫 키 그대로)
  const big = new Float32Array([0, 0, 0, 1, 0, Math.sin(h(90)), 0, Math.cos(h(90))]);
  const m2 = lerpQuat(q(), big, 0, 4, 0.5);
  assert.ok(Math.abs((2 * Math.asin(m2.y) * 180) / Math.PI - 45) < 1e-4);   // 큰 각은 slerp
  const neg = new Float32Array([0, 0, 0, 1, 0, -Math.sin(h(10)), 0, -Math.cos(h(10))]);   // 반대 부호 키 — 짧은 쪽으로
  const m3 = lerpQuat(q(), neg, 0, 4, 0.5);
  assert.ok(Math.abs((2 * Math.asin(m3.y) * 180) / Math.PI - 5) < 1e-3);
});

console.log(`${n}개 통과`);
