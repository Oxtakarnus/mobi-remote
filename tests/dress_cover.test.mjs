// 드레스룸 가림 판정 시험 (node tests/dress_cover.test.mjs) — web/dressroom/cover.js
import assert from 'node:assert/strict';
import { coverage, eyeVisible, gameSlot, outside, seamRule, uncut } from '../web/dressroom/cover.js';

const part = (slot, o = {}) => ({ slot, rules: null, hoods: [], cover: 0, ...o });
let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };

t('후드 없는 옷이면 후드를 켜도 그대로', () => {
  const c = coverage([part('Top'), part('Helmet', { cover: 2 })], { hood: true });
  assert.equal(c.canHood, false);
  assert.equal(c.hood, 'off');
  assert.equal(c.hair, 2);
  assert.equal(c.hidden.has('Helmet'), false);
});

t('후드를 쓰면 모자를 숨기고 머리는 5단계', () => {
  const c = coverage([part('OnePiece', { hoods: ['off', 'on'] }), part('Helmet', { cover: 2, rules: { hide: ['Accessory2'] } })], { hood: true });
  assert.equal(c.hood, 'on');
  assert.equal(c.hair, 5);
  assert.ok(c.hidden.has('Helmet'));
  assert.equal(c.hidden.has('Accessory2'), false);   // 숨긴 모자의 규칙은 안 쓴다
});

t('벗은 후드는 머리가 누르는 단계면 눌린 모양', () => {
  const coat = part('Robe', { hoods: ['off', 'pressed', 'on'] });
  assert.equal(coverage([coat, part('Hair', { rules: { press: [0, 1] } })]).hood, 'pressed');
  assert.equal(coverage([coat, part('Hair', { rules: { press: [0, 1] } }), part('Helmet', { cover: 3 })]).hood, 'off');
  assert.equal(coverage([coat, part('Hair', { rules: { press: 'all' } }), part('Helmet', { cover: 3 })]).hood, 'pressed');
  assert.equal(coverage([part('Robe', { hoods: ['off', 'on'] }), part('Hair', { rules: { press: 'all' } })]).hood, 'off');
});

t('덮개 규칙은 덮개를 닫았을 때만, 자기 부위는 숨기지 않는다', () => {
  const helmet = part('Helmet', { rules: { hide: ['Helmet', 'Hair'], cap: ['Eye', 'Beard'] } });
  const open = coverage([helmet]);
  assert.deepEqual([...open.hidden].sort(), ['Hair']);
  assert.equal(open.canCap, true);
  const closed = coverage([helmet], { cap: true });
  assert.deepEqual([...closed.hidden].sort(), ['Beard', 'Eye', 'Hair']);
});

t('자기 부위를 숨기라는 옷은 그 부위를 대신 차지한다 — 가발이 원래 머리를 숨긴다', () => {
  const wig = part('Hair', { rules: { hide: ['Hair'] } });
  const c = coverage([part('Hair'), wig, part('Top')]);
  assert.deepEqual(c.shown, [false, true, true]);
  assert.equal(c.hidden.has('Hair'), false);   // 부위째 숨긴 것은 아니다
  const helmet = part('Helmet', { rules: { hide: ['Helmet', 'Hair'] } });
  assert.deepEqual(coverage([helmet, part('Hair')]).shown, [true, false]);
});

t('로브는 상의·하의·한 벌·백팩을 숨기고 그 규칙도 안 쓴다', () => {
  const c = coverage([part('Robe'), part('Top', { rules: { hide: ['Hair'] } }), part('Shoes')]);
  assert.ok(c.hidden.has('Top') && c.hidden.has('Bottom') && c.hidden.has('OnePiece') && c.hidden.has('AccessoryBody0'));
  assert.equal(c.hidden.has('Hair'), false);
  assert.equal(c.hidden.has('Shoes'), false);
  // 백팩은 로브 칸에 입지만 게임 부위가 달라 옷을 숨기지 않는다
  const bag = coverage([part('AccessoryBody0'), part('Top')]);
  assert.equal(bag.hidden.has('Top'), false);
});

t('눈 메시 — 한쪽만 가리면 그쪽 흰자만, 눈동자는 두 눈 다 가렸을 때', () => {
  const right = new Set(['RightEye', 'RightEyebrow']);
  assert.equal(eyeVisible('Mesh_EyeBase_R', right), false);
  assert.equal(eyeVisible('Mesh_EyeBase_L', right), true);
  assert.equal(eyeVisible('Mesh_EyeBall', right), true);
  assert.equal(eyeVisible('Mesh_EyeBrow', right), true);
  const both = new Set(['LeftEye', 'RightEye', 'LeftEyebrow', 'RightEyebrow']);
  assert.equal(eyeVisible('Mesh_EyeHigh', both), false);
  assert.equal(eyeVisible('Mesh_EyeBrow', both), false);
});

t('입 모양 — 숨지 않은 장식의 칸, 없으면 0', () => {
  const gum = part('FaceDeco', { rules: { mouth: 32 } });
  assert.equal(coverage([part('Top'), gum]).mouth, 32);
  assert.equal(coverage([part('Top')]).mouth, 0);
  const mask = part('Helmet', { rules: { hide: ['FaceDeco'] } });
  assert.equal(coverage([mask, gum]).mouth, 0);   // 가려진 장식은 입을 안 바꾼다
});

t('겹침 순서 — 같은 이음새면 큰 쪽, 같으면 부위 순위, 이음새가 안 겹치면 모른다', () => {
  const boots = { slot: 'Foot', junctions: { AnkleSize: 'Medium' } };
  const coat = { slot: 'OnePiece', junctions: { WristSize: 'Medium', AnkleSize: 'Medium' } };
  const flare = { slot: 'Bottom', junctions: { WaistSize: 'Medium', AnkleSize: 'Highest' } };
  const gloves = { slot: 'Hand', junctions: { WristSize: 'Lowest' } };
  assert.equal(outside(boots, coat), true);     // 발목 같음 → 신발(8) > 한 벌(7)
  assert.equal(outside(coat, boots), false);
  assert.equal(outside(flare, boots), true);    // 나팔바지 발목이 더 크다
  assert.equal(outside(coat, gloves), true);    // 손목 Medium > Lowest — 소매가 장갑 위
  assert.equal(outside(boots, gloves), false);  // 겹치는 이음새 없음
  assert.equal(outside({ slot: 'Robe', junctions: {} }, gloves), true);   // 로브는 늘 견준다
  assert.equal(outside(null, coat), false);
  assert.equal(outside({ slot: 'Robe', junctions: {} }, { slot: 'Hair', junctions: {} }), false);   // 이음새 없는 머리·모자는 안 낀다
  assert.equal(outside({ slot: 'AccessoryBody0', junctions: {} }, coat), false);
});

t('자르는 판 예외 — 치마는 신발이, 상의 겉옷은 하의·신발이 안 자른다', () => {
  assert.equal(uncut('Mesh_Skirt_01', 'OnePiece', 'Foot'), true);
  assert.equal(uncut('Mesh_Bottom_00', 'OnePiece', 'Foot'), false);
  assert.equal(uncut('Mesh_Skirt_01', 'OnePiece', 'Hand'), false);
  assert.equal(uncut('Mesh_Outer_00', 'Top', 'Bottom'), true);
});

t('판 특례 — 허리 판은 신발·하의(상의를 자를 때)면 아래로, 한 벌·로브·상의면 가슴까지', () => {
  assert.deepEqual(seamRule('Body', 'Foot'), { waistDown: true, waistUp: false, hipUp: false, dropTorso: false });
  assert.deepEqual(seamRule('Top', 'Bottom'), { waistDown: true, waistUp: false, hipUp: false, dropTorso: false });
  assert.deepEqual(seamRule('Body', 'Robe'), { waistDown: false, waistUp: true, hipUp: true, dropTorso: true });
  assert.deepEqual(seamRule('Body', 'Top'), { waistDown: false, waistUp: true, hipUp: false, dropTorso: false });
  assert.deepEqual(seamRule('Body', 'Bottom'), { waistDown: false, waistUp: false, hipUp: false, dropTorso: false });
  assert.deepEqual(seamRule('Bottom', 'Robe'), { waistDown: false, waistUp: false, hipUp: false, dropTorso: false });   // 옷끼리는 상의·하의만
  assert.equal(seamRule('Body', undefined).waistUp, false);
});

t('장식 부위 이름', () => {
  assert.equal(gameSlot('EyeDeco'), 'Accessory1');
  assert.equal(gameSlot('Helmet'), 'Helmet');
  assert.equal(gameSlot('Robe', { slot: 'AccessoryBody0', junctions: {} }), 'AccessoryBody0');   // 모델 정의 부위가 먼저
  assert.equal(gameSlot('Shoes', { slot: 'Foot', junctions: {} }), 'Foot');
  assert.equal(gameSlot('EarDeco', null), 'Accessory2');
});

console.log(`${n}개 통과`);
