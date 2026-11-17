// 드레스룸 조립 시험 (node tests/dress_dresser.test.mjs) — web/dressroom/dresser.js 의 모델 없이 되는 부분
import assert from 'node:assert/strict';
import { Dresser, cleanColors } from '../web/dressroom/dresser.js';
import { FaceTable, emptyFace } from '../web/dressroom/face.js';

let n = 0;
const t = (name, fn) => { fn(); n++; console.log('PASS', name); };

const FACE = {
  heads: [{ id: 1, m: { Female: 'Face_F_01' } }], eyes: [], mouths: [{ id: 5, m: { 1: { Female: 'Mouth_F_05' } } }],
  ftats: [], btats: [{ id: 9, m: { Female: 'Tat_F_09' } }], beards: [],
  parts: { Female_Hair_Two: { ch: ['Hair', 'Hair1', null] }, Female_Hair_One: { ch: ['Hair', null, 'HairAccessory'] } },
  colors: {},
};
const fakeModel = (id) => ({ id });
function dresser() {
  return new Dresser({ url: async (id) => id, scene: { add() {}, remove() {}, root() {} }, ft: new FaceTable(FACE),
    bodies: [{ id: 'Female', folder: 'Female' }, { id: 'Girl', folder: 'Infant' }] });
}

t('색 칸 정리', () => {
  assert.deepEqual(cleanColors(['#aabbcc', null]), ['#AABBCC', null]);
  assert.equal(cleanColors([]), null);
  assert.equal(cleanColors(['red']), null);
  assert.equal(cleanColors(new Array(7).fill(null)), null);
});

t('체형 폴더와 입을 수 있는 품목', () => {
  const d = dresser();
  d.body = 'Girl';
  assert.equal(d.folder(), 'Infant');
  assert.equal(d.fits({ folder: 'Infant' }), true);
  assert.equal(d.fits({ folder: 'Female' }), false);
  assert.equal(d.fits({ folder: '' }), true);   // 체형 공용 (패션 무기)
});

t('얼굴 메시 id — 고른 것, 없으면 체형 기본', () => {
  const d = dresser();
  d.body = 'Female';
  assert.equal(d.meshId('heads'), 'head:Female');   // 안 골랐으면 체형 기본
  d.face = { ...emptyFace(), heads: 1 };
  assert.equal(d.meshId('heads'), 'face:Face_F_01');
  assert.equal(d.meshId('eyes'), 'eye:Female');
  assert.equal(d.meshId('beards'), null);
});

t('머리 색 칸 — 칸 이름대로 옮기기·투톤', () => {
  const d = dresser();
  const prev = { item: { id: 'Female_Hair_One' }, colors: ['#111111', '#222222', '#333333'] };
  assert.deepEqual(d.hairSlots(prev), [[0, 'Hair'], [2, 'HairAccessory']]);
  assert.deepEqual(d.carryHair(prev, { id: 'Female_Hair_Two' }), ['#111111', '#111111', null]);   // Hair1 은 Hair 색
  assert.equal(d.twoTone('Female_Hair_Two'), true);
  assert.equal(d.twoTone('Female_Hair_One'), false);
  d.worn.Hair = prev;
  assert.equal(d.hairColor(), '#111111');
});

t('쓰인 모델 목록 — 몸·얼굴·데칼·입은 것 (동작 클립은 뺀다)', () => {
  const d = dresser();
  d.body = 'Female';
  d.shape = 'Fat';
  d.face = { ...emptyFace(), mouths: 5, btats: 9 };
  d.base = [fakeModel('body:Female'), fakeModel('face:Face_F_01'), fakeModel('eye:Female')];
  d.fit = {};
  d.worn = { Top: { item: { id: 'Female_A_Top_00' }, model: fakeModel('Female_A_Top_00') }, Shoes: { item: { id: 'x' }, model: null } };
  d.steps = [{ body: 'HF@Bye', face: 'HF@Bye_Facial' }];
  assert.deepEqual(d.used(), [
    { id: 'body:Female', role: 'body' }, { id: 'face:Face_F_01', role: 'head' }, { id: 'eye:Female', role: 'eye' },
    { id: 'bdc:Female', role: 'bdc' },
    { id: 'decal:Mouth_F_05', role: 'decal', kind: 'mouths', where: 'lips' },
    { id: 'decal:Tat_F_09', role: 'decal', kind: 'btats', where: 'body' },
    { id: 'Female_A_Top_00', role: 'item', part: 'Top' },   // 아직 불러오는 옷은 빼고
  ]);
});

t('옷 기본색 — 게임 시트 기본 염색이 먼저, 시트에 없는 칸은 재질 색', () => {
  const d = dresser();
  const model = { defaults: () => ['#957334', '#C1BCB6', '#752818'] };   // 재질 기본색 (칸 3개)
  const w = { item: { colors: ['#35414D', null, '#D66869', '#8F8F8F', '#EEEFEA', '#897C5A'] }, model };
  assert.deepEqual(d.defaultColors(w), ['#35414D', '#C1BCB6', '#D66869']);   // 칸 수는 모델 것
  assert.deepEqual(d.defaultColors({ item: {}, model }), ['#957334', '#C1BCB6', '#752818']);   // 시트에 없는 옷
  assert.equal(d.defaultColors({ item: {}, model: { defaults: () => null } }), null);         // 염색 불가
  assert.equal(d.defaultColors({ item: {}, model: null }), null);                              // 아직 못 불렀다
});

console.log(`${n}개 통과`);
