// 드레스룸 화면 — 화면 상태(S)·조립(Dresser) 연결·매 프레임·탭과 툴바·기억(설정 파일 'dressroom') 저장과 되살리기.
// 모델 조립(체형·얼굴·옷·몸 조절·가림·동작·무기·흔들림)은 dresser.js, 왼쪽 목록 칸은 list.js, 오른쪽 옷 카드는 cards.js,
// 코디·기억 값 검사는 looks.js, 화면 설정 판은 view.js. 파이썬 쪽은 gui_app/dressroom.py 의 DressApi (ui.js rpc).
import { Stage, TATTOO_GRAY } from './viewer.js';
import { FaceTable, MESH, DECAL, emptyFace, cleanFace } from './face.js';
import { ColorBox } from './colors.js';
import { ViewPanel, cleanView, FOV, GAZE_TIP, GAZE_REST } from './view.js';
import { MotionTable } from './motion.js';
import { Dresser, cleanColors } from './dresser.js';
import { Life } from './life.js';
import { Backdrop } from './backdrop.js';
import { $, esc, rpc, flash } from './ui.js';
import { IconLoader } from './icons.js';
import { ItemList, MODES, LOOK_SUBS, WEAR_SUBS, CLOTHES, label } from './list.js';
import { WornCards, LOOK_PARTS } from './cards.js';
import { SHAPES, LOOK_MAX, cleanLook, cleanShape, cleanSkin, cleanWorn, cleanName, okAge, okHeight, perBody } from './looks.js';

// 머리 염색 칸 이름(face.json 부품 ch) → [색 상자 이름, 게임 색 표, 투톤, 한 색 줄만] — 투톤은 투톤 머리(twoTone)일 때만
const HAIR_SLOT = { Hair: ['머리', 'hair', true, false], Hair1: ['두 번째', 'hair', false, true], HairAccessory: ['장식', 'hairacc', false, false] };
// 탭을 옮기면 카메라가 갈 곳 (화면 설정 '탭 전환 시 카메라 이동')
const SHOT_OF = { body: 'full', hair: 'face', eye: 'face', mouth: 'face', head: 'face', face: 'face', mark: 'full',
  Helmet: 'upper', Top: 'upper', Bottom: 'full', Gloves: 'upper', Shoes: 'feet', Robe: 'full', FaceDeco: 'face', EyeDeco: 'face', EarDeco: 'face',
  Weapon: 'full' };
const FAV_MAX = 500;
const RECENT_MAX = 60;
const ITEM_COLORS_MAX = 300;
const S = {
  cat: null, q: '',
  mode: 'wear', subs: { look: 'body', wear: 'Top', motion: 'common' },   // 왼쪽 탭 · 탭마다 하위 탭
  gaze: true, moreOpen: false, full: false,
  view: cleanView(null),   // 화면 설정 (view.js)
  ages: {}, heights: {},   // 체형 → 나이 · 키 조절값(-1..1)
  faces: {},     // 체형 → 얼굴 고른 값 (face.js emptyFace)
  fav: [],       // 즐겨찾기 의상 id
  recent: [],    // 최근 입은 의상 id (앞이 최근)
  looks: [],     // 저장한 코디 [{name, body, shape, age, height, skin, face, worn}]
  motion: null,  // 동작 탭에서 고른 동작 id (기억 안 함 — 창을 열면 늘 대기 동작)
  expr: null,    // 동작 탭 표정 갈래에서 고른 표정 id (기억 안 함 — 동작과 따로, 동작 위에 얹는다)
  bundle: null,  // 마지막으로 띄운 모습 {look, models, motion, expr} (기억 — 다른 프로그램이 설정 파일에서 읽는다)
  outfits: {},   // 체형 → {부위: {id, colors}} (기억)
  itemColors: {},   // 의상 id → 마지막에 칠한 색 (기본색과 다를 때만, 기억 — ITEM_COLORS_MAX 개)
};
const life = new Life();
let FT = new FaceTable(null);     // 얼굴 선택지 표 (목록을 받은 뒤)
let MT = new MotionTable(null);   // 동작 표 (목록을 받은 뒤)
// 모델 조립 — 지금 체형·셰이프·피부·얼굴·나이·키·입은 것·동작 (목록을 받으면 체형·의상·얼굴 표를 넣는다)
const D = new Dresser({
  url: modelUrl,
  scene: { add: (m) => stage.add(m), remove: (m) => stage.remove(m), root: (o, on) => (on ? stage.scene.add(o) : stage.scene.remove(o)) },
  ft: FT,
  remembered: (item) => S.itemColors[item.id] || null,
  on: { change: dressChanged, error: dressError, busy },
});
const bad = new Set();   // 못 읽은 모델 (이번 창에서만)
const icons = new IconLoader($('#list'));
const list = new ItemList({ S, D, bad, icons, ft: () => FT, mt: () => MT, face: () => faceOf() });
const cards = new WornCards($('#worn'), $('#worn-empty'), D, { takeOff, colorsDone: (w) => { rememberColors(w); save(); } });
let stage = null;
let backdrop = null;   // 무대·조명
let busyN = 0;
let errTimer = 0;

function busy(d) {
  busyN = Math.max(0, busyN + d);
  $('#busy').classList.toggle('hidden', !busyN);
}

function showErr(msg, sticky = false) {
  const el = $('#err');
  el.textContent = msg;
  el.title = '눌러서 닫기';
  el.classList.remove('hidden');
  clearTimeout(errTimer);
  if (!sticky) errTimer = setTimeout(() => el.classList.add('hidden'), 8000);
}

async function modelUrl(id) {
  const r = await rpc('model', id);
  if (!r || r.error) throw new Error((r && r.error) || '모델을 꺼내지 못했습니다');
  return r.url;
}

// ── 나이·키 ──
function paintFit() {
  const f = D.fit;
  $('#ages').classList.toggle('hidden', !f);
  $('#height-row').classList.toggle('hidden', !f);
  if (!f) return;
  const ages = [];
  for (let a = f.minAge; a <= f.maxAge; a++) ages.push(a);
  $('#ages').innerHTML = ages.map((a) => `<button data-age="${a}" class="${a === f.state.age ? 'on' : ''}">${a}세</button>`).join('');
  $('#height').value = S.heights[D.body] || 0;
  $('#height-cm').textContent = f.state.cm.toFixed(1) + 'cm';
}

/** 나이·키를 바꾼 뒤 — dragging 이면 뼈만, 아니면 옷 맞추기·키 재기까지. reframe 이면 카메라도 새 키에 맞춘다. */
function fitChanged(dragging, reframe = false) {
  D.applyFit();
  paintFit();
  if (dragging) return;
  D.refit();
  if (reframe) stage.fit(D.rig, restPose); else stage.measure(D.rig, restPose);
  save();
}

function setHeight(v, dragging) {
  S.heights[D.body] = D.height = v;
  fitChanged(dragging);
}

/** 후드 쓰기 · 투구 덮개 닫기 (key 'hood' | 'cap'). */
function setCover(key, on) {
  D.setCover(key, on);
  save();
}

// ── 동작·표정 ──
/** 지금 동작 — 동작 탭에서 고른 것이 이 체형에 있으면 그것(셰이프 것), 아니면 꾸미기 화면 대기 동작.
 *  무기 상태는 Dresser 가 동작에 맞춘다 (play 의 weapon). 고른 동작을 못 불러오면 고른 것을 풀고 대기 동작으로. */
async function loadAnim() {
  const steps = S.motion ? MT.steps(S.motion, D.folder(), D.shape) : null;
  if (steps) busy(1);
  try {
    await D.play(steps, MT.weapon(S.motion));
  } catch (e) {
    showErr('동작을 불러오지 못했습니다: ' + e.message);
    S.motion = null;
    paintList();
    await D.play(null);
  } finally {
    if (steps) busy(-1);
    paintActing();
  }
}

/** 지금 표정 — 표정 갈래에서 고른 것을 이 체형 것으로 (없으면 끈다). */
function loadExpr() {
  D.setExpr(S.expr ? MT.faceStem(S.expr, D.folder()) : null).catch((e) => showErr('표정을 불러오지 못했습니다: ' + e.message));
}

/** 동작 탭에서 고르기 — 고른 것을 다시 누르면 대기 동작으로. 표정은 따로 켜고 끈다. */
function pickMotion(id) {
  if (MT.isFace(id)) {
    S.expr = S.expr === id ? null : id;
    paintList();
    loadExpr();
    save();
    return;
  }
  S.motion = S.motion === id ? null : id;
  if (S.motion && !D.move) D.setMove(true);
  paintToggles();
  paintList();
  loadAnim();
  save();
}

/** 시선이 카메라를 따라가나 — 켜 두었고 고른 동작을 틀지 않을 때 (고른 동작 중엔 머리·눈을 동작·표정에 맡긴다). */
const gazeOn = () => S.gaze && !D.acting;

/** 매 프레임 — 자세(기본 → 동작 → 몸 조절) → 시선·깜빡임 → 옷·머리 흔들림 → 의상 이펙트 (Dresser 머리 설명의 차례). */
function tick(dt) {
  if (!D.rig) return;
  D.pose(dt);
  life.gaze = gazeOn();
  life.update(dt, D.rig, stage.camera, D.base[MESH.eyes] || null);
  D.physics(dt);
  D.effects(dt, stage.camera);
}

// ── 기억 (설정 파일 'dressroom') ──
let saveTimer = 0;
/** 지금 입은 것 {부위: {id, colors}}. 체형을 세우는 중이면 그 체형에 입힐 코디에 지금 입은 것을 얹는다
 *  (옷을 벗기고 몸을 불러오는 사이에 저장이 돌아도 기억이 비지 않게 — Dresser.pending). */
function currentOutfit() {
  const worn = Object.fromEntries(Object.entries(D.worn).map(([p, w]) => [p, { id: w.item.id, colors: w.colors }]));
  return D.pending && D.pending.rig === D.rig ? { ...D.pending.outfit, ...worn } : worn;
}

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 400);
}

function saveNow() {
  clearTimeout(saveTimer);
  if (D.body) S.outfits[D.body] = currentOutfit();
  return rpc('save_prefs', { body: D.body, shape: D.shape, skin: D.skin, mode: S.mode, subs: S.subs, outfits: S.outfits,
    gaze: S.gaze, hood: D.hood, cap: D.cap, weaponHide: D.weaponHide, itemColors: S.itemColors, ages: S.ages, heights: S.heights, looks: S.looks, faces: S.faces, fav: S.fav, recent: S.recent,
    view: S.view, bundle: bundleState() })
    .catch(() => {});
}

/** 지금 모습 — 다른 프로그램이 설정 파일(dressroom.bundle)에서 읽어 이 모습을 다시 꺼낸다.
 *  몸을 세우는 중이면 전 값 그대로 (다 불러오면 다시 저장한다). */
function bundleState() {
  if (D.base[0] && !D.pending) S.bundle = { look: currentLook(''), models: D.used(), motion: S.motion, expr: S.expr };
  return S.bundle;
}

// ── 체형 ──
/** 체형을 바꾸고 그 체형에서 입던 옷(outfit 을 주면 그것)을 입힌다. 목록에 없어 못 입힌 옷 수를 돌려준다. */
async function setBody(body, outfit = null) {
  if (body === D.body && !outfit) return 0;
  if (D.body) S.outfits[D.body] = currentOutfit();
  const want = outfit || S.outfits[body] || {};
  if (outfit) S.outfits[body] = outfit;
  const miss = await D.setBody(body, { worn: want, face: faceOf(body), age: S.ages[body] ?? null, height: S.heights[body] || 0, starter: !outfit });
  if (D.body === body && D.age != null) S.ages[body] = D.age;   // 처음 보는 체형은 체형 기본 나이를 기억
  save();
  return miss;
}

/** 조립 알림 (Dresser on.change) → 화면 갱신. */
function dressChanged(what) {
  if (what === 'body') { paintFit(); paintBodies(); paintList(); paintToggles(); }
  else if (what === 'framed') { paintFit(); stage.fit(D.rig, restPose); loadAnim(); loadExpr(); save(); }
  else if (what === 'worn') wornChanged();
  else if (what === 'cover') paintToggles();
  else if (what === 'weapon') { paintToggles(); save(); }
  else if (what === 'face') { paintColors(); save(); }
}

/** 입은 것이 바뀐 뒤 — 오른쪽 카드, 목록의 입은 표시 (최근 입은 옷 탭은 순서가 바뀌니 다시 그린다), 머리 색 상자, 기억. */
function wornChanged() {
  cards.paint();
  if (S.mode === 'wear' && sub() === '__recent') paintList();
  else { list.markWorn($('#list')); paintColors(); }
  save();
}

/** 조립 중 오류 — 옷이면 목록에 못 읽은 옷으로 표시한다. */
function dressError(msg, item) {
  if (item) { bad.add(item.id); showErr(label(item) + ': ' + msg); } else showErr(msg);
}

const restPose = () => D.restPose();

// ── 얼굴 ──
const faceOf = (body = D.body) => S.faces[body] || (S.faces[body] = emptyFace());

/** 고른 얼굴 하나를 바꾼다 (id null = 기본·없음). */
function setFace(kind, id) {
  const f = faceOf();
  if (f[kind] === id) return;
  f[kind] = id;
  if (kind in MESH) D.swapMesh(kind);        // 얼굴형이면 새 얼굴에 데칼까지
  else if (kind in DECAL) D.faceDecals();
  paintList();
  save();
}

// ── 외형 색 (왼쪽 색 상자) ──
const colorBox = new ColorBox($('#colors'), setLookColor);

/** 색 상자 — 외형 탭이면 지금 하위 탭의 색 칸, 아니면 숨김. */
function paintColors() {
  colorBox.show(S.mode === 'look' && S.cat ? colorSets(sub()) : []);
}

const irisMat = () => {
  const eye = D.base[MESH.eyes];
  return eye && eye.mats.find((m) => m.userData.eye === 'iris' && m.userData.info.kind === 'dye');
};

/** 하위 탭 → 색 칸들 (colors.js). */
function colorSets(k) {
  const f = faceOf();
  if (k === 'body') return [{ id: 'skin', label: '피부', pal: 'skin', get: () => D.skin || D.skinBase }];
  if (k === 'eye') {
    const iris = irisMat();
    return iris ? [{ id: 'eye', label: '눈동자', pal: 'eye', get: () => f.eye || iris.userData.info.dye[0] }] : [];
  }
  if (k === 'hair') {
    const w = D.worn.Hair;
    if (!w || !w.model || !w.colors) return [];
    const tt = D.twoTone(w.item.id);
    return D.hairSlots(w).map(([i, name]) => {
      const [title, pal, two, one] = HAIR_SLOT[name] || ['칸 ' + (i + 1), null, false, false];
      return { id: 'hair:' + i, label: title, pal, two: two && tt, one: one || (two && !tt), get: () => w.colors[i] };
    });
  }
  const kind = k === 'face' ? 'ftats' : k === 'mark' ? 'btats' : null;
  const n = kind && FT.model(kind, f, D.body);
  const p = n && FT.part(n);
  return p && p.dye ? [{ id: 'tat', label: '문양', pal: null, get: () => f.tat || TATTOO_GRAY }] : [];
}

/** 색 상자에서 고른 색 (hex null = 기본색, hex2 = 투톤 머리의 두 번째 색). */
function setLookColor(id, hex, hex2, done) {
  const f = faceOf();
  if (id === 'skin') {
    D.setSkin(hex);
  } else if (id === 'eye') {
    f.eye = hex;
    D.faceColors();
  } else if (id === 'tat') {
    D.setTat(hex);
  } else if (id.startsWith('hair:')) {   // 머리는 카드가 없다 — 색 상자에서만 (눈썹·수염도 따라간다)
    const w = D.worn.Hair;
    if (!w || !w.model) return;
    const i = +id.slice(5);
    D.setDye('Hair', i, hex || (D.defaultColors(w) || [])[i] || w.colors[i]);
    const second = hex2 && D.hairSlots(w).find(([, name]) => name === 'Hair1');
    if (second) D.setDye('Hair', second[0], hex2);
  }
  colorBox.refresh();
  if (done) save();
}

// ── 코디 (저장·파일) ──
function currentLook(name) {
  return { name, body: D.body, shape: D.shape, age: D.fit ? D.fit.state.age : null, height: S.heights[D.body] || 0,
    skin: D.skin, face: { ...faceOf() }, worn: currentOutfit() };
}

/** 코디 입히기 — 체형·셰이프·나이·키·피부·옷 전부. */
async function useLook(L) {
  D.shape = L.shape;
  paintShapes();
  D.skin = L.skin;
  if (L.age != null) S.ages[L.body] = L.age;
  S.heights[L.body] = L.height;
  if (L.face) S.faces[L.body] = { ...L.face };
  const miss = await setBody(L.body, L.worn);
  if (miss) showErr(`목록에 없는 옷 ${miss}개는 빼고 입혔습니다`);
}

/** 저장 목록에 넣는다 (같은 이름은 바꾼다). */
function keepLook(L) {
  const at = S.looks.findIndex((x) => x.name === L.name);
  if (at >= 0) S.looks[at] = L; else S.looks.push(L);
  if (S.looks.length > LOOK_MAX) S.looks.splice(0, S.looks.length - LOOK_MAX);
  save();
}

function lookName() {
  const typed = cleanName($('#look-name').value);
  if (typed) return typed;
  const body = S.cat.bodies.find((b) => b.id === D.body);
  return (body ? body.name : '') + ' 코디 ' + (S.looks.length + 1);
}

/** 코디 지우기 — 두 번 눌러야 지운다. */
function delLook(b) {
  const i = +b.dataset.del;
  if (!S.looks[i]) return;
  if (b.dataset.sure !== '1') {
    b.dataset.sure = '1';
    b.textContent = '지우기?';
    setTimeout(() => { if (b.isConnected) { b.dataset.sure = ''; b.textContent = '×'; } }, 1500);
    return;
  }
  S.looks.splice(i, 1);
  paintList();
  save();
}

// ── 입기·벗기 ──
/** 옷 색 기억 — 기본색과 같으면 지운다. 오래된 것부터 ITEM_COLORS_MAX 개만 남긴다. */
function rememberColors(w) {
  if (!w || !w.model || LOOK_PARTS.includes(w.item.part) || !w.colors) return;
  const id = w.item.id;
  const def = D.defaultColors(w) || [];
  delete S.itemColors[id];
  if (w.colors.some((c, i) => c && c !== def[i])) S.itemColors[id] = w.colors.slice();
  const ids = Object.keys(S.itemColors);
  for (const k of ids.slice(0, Math.max(0, ids.length - ITEM_COLORS_MAX))) delete S.itemColors[k];
}

/** 최근 입은 옷에 넣는다 (목록에서 골라 입을 때만 — 코디·체형 바꾸기로 입힌 것은 안 넣는다). */
function noteRecent(item) {
  if (!CLOTHES.includes(item.part)) return;
  S.recent = [item.id, ...S.recent.filter((x) => x !== item.id)].slice(0, RECENT_MAX);
}

function takeOff(part) {
  if (D.takeOff(part)) wornChanged();
}

/** 세트를 다 입는다 (지금 체형의 같은 세트 이름 의상). */
function wearSet(name) {
  for (const i of list.setItems(name)) { noteRecent(i); D.wear(i); }
}

function toggleFav(id) {
  S.fav = S.fav.includes(id) ? S.fav.filter((x) => x !== id) : [id, ...S.fav].slice(0, FAV_MAX);
  paintList();
  save();
}

// ── 왼쪽 ──
function paintBodies() {
  $('#bodies').innerHTML = S.cat.bodies.map((b) => `<button data-body="${esc(b.id)}" class="${b.id === D.body ? 'on' : ''}">${esc(b.name)}</button>`).join('');
}

function paintShapes() {
  $('#shapes').innerHTML = SHAPES.map(([k, n]) => `<button data-shape="${k}" class="${k === D.shape ? 'on' : ''}">${n}</button>`).join('');
}

const sub = () => S.subs[S.mode];

function paintTabs() {
  const modes = MODES.filter(([k]) => k !== 'motion' || MT.ok);
  if (!modes.some(([k]) => k === S.mode)) S.mode = 'wear';
  $('#modes').innerHTML = modes.map(([k, n]) => `<button data-mode="${k}" role="tab" class="${k === S.mode ? 'on' : ''}">${n}</button>`).join('');
  const subs = list.subsOf(S.mode);
  if (subs.length && !subs.some(([k]) => k === sub())) S.subs[S.mode] = subs[0][0];
  $('#subs').classList.toggle('hidden', !subs.length);
  $('#subs').innerHTML = subs.map(([k, n]) => `<button data-sub="${k}" role="tab" class="${k === sub() ? 'on' : ''}">${n}</button>`).join('');
}

/** 탭을 옮기면 카메라도 그 부위로 (화면 설정 '탭 전환 시 카메라 이동'). */
function tabShot() {
  if (S.view.tabCam && stage && S.mode !== 'looks') stage.shot(SHOT_OF[sub()] || 'full');
}

/** 왼쪽 목록 — 지금 탭·하위 탭에 맞게. */
function paintList() {
  paintTabs();
  const mode = S.mode, k = sub(), q = S.q.trim().toLowerCase();
  const isBody = mode === 'look' && k === 'body';
  $('#body-box').classList.toggle('hidden', !isBody);
  $('#looks-box').classList.toggle('hidden', mode !== 'looks');
  $('#search').classList.toggle('hidden', isBody);
  $('#search').placeholder = mode === 'wear' ? '모든 부위에서 찾기' : mode === 'motion' ? '모든 동작에서 찾기' : '이름 검색';
  let { html, n, title } = list.html(mode, k, q);
  const box = $('#list');
  box.innerHTML = html;
  paintColors();
  if (n == null) n = box.querySelectorAll('.tile[data-fid]:not([data-fid=""])').length;
  $('#sub-title').textContent = title;
  $('#count').textContent = n >= 0 ? n.toLocaleString() : '';
  icons.watch();
}

function setTab(key, value) {
  if (key === 'mode') S.mode = value; else S.subs[S.mode] = value;
  S.q = '';
  $('#search').value = '';
  paintList();
  tabShot();
  save();
}

// ── 툴바 ──
function paintToggles() {
  $('#move').classList.toggle('on', D.move);
  const rest = D.acting;   // 고른 동작 중엔 시선이 쉰다 (gazeOn)
  $('#gaze').disabled = rest;
  $('#gaze').classList.toggle('on', gazeOn());
  $('#gaze').title = rest ? GAZE_REST : GAZE_TIP;
  const c = D.cover;
  $('#hood').classList.toggle('hidden', !(c && c.canHood));
  $('#hood').classList.toggle('on', D.hood);
  $('#cap').classList.toggle('hidden', !(c && c.canCap));
  $('#cap').classList.toggle('on', D.cap);
  $('#weapon').classList.toggle('hidden', !D.hasWeapon);
  $('#weapon').classList.toggle('on', !D.weaponHide);
}

/** 동작을 틀고 멈춘 뒤 — 시선 단추가 잠기고 풀린다 (툴바·옵션 판). */
function paintActing() {
  paintToggles();
  if (panel.open) panel.paint();
}

function setGaze(on) {
  S.gaze = on;
  paintActing();
  save();
}

async function fullscreen(on) {
  try {
    const r = await rpc('fullscreen', on);
    if (r && !r.error) S.full = !!r.on;
  } catch (_) { /* 창이 없다 */ }
  if (panel.open) panel.paint();
}

// ── 화면 설정 ──
function applyView() {
  stage.setView({ scale: S.view.scale, fps: S.view.fps, pauseBlur: S.view.pauseBlur, wire: S.view.wire, shadow: S.view.shadow });
  backdrop.set({ scene: S.view.scene, light: S.view.light, reflect: S.view.reflect });
  stage.setFov(FOV[S.view.fov]);
}

const panel = new ViewPanel($('#viewp'), {
  get: () => S.view,
  set: async (v) => {
    const reopen = 'aa' in v && v.aa !== S.view.aa;   // 계단 줄이기는 3D 화면을 새로 만들어야 바뀐다
    S.view = cleanView({ ...S.view, ...v });
    if (reopen) { await saveNow(); location.reload(); return; }
    applyView();
    if ('fov' in v) stage.front();
    save();
  },
  gaze: () => S.gaze,
  gazeRest: () => D.acting,
  setGaze,
  fullscreen: () => fullscreen(),
  isFull: () => S.full,
});

// ── 시작 ──
function wire() {
  $('#bodies').addEventListener('click', (e) => {
    const b = e.target.closest('[data-body]');
    if (b) setBody(b.dataset.body);
  });
  $('#shapes').addEventListener('click', (e) => {
    const b = e.target.closest('[data-shape]');
    if (!b) return;
    D.setShape(b.dataset.shape);
    paintShapes();
    paintFit();
    if (D.fit) stage.measure(D.rig, restPose);
    loadAnim();
    save();
  });
  $('#ages').addEventListener('click', (e) => {
    const b = e.target.closest('[data-age]');
    if (!b || !D.fit) return;
    S.ages[D.body] = D.age = +b.dataset.age;
    fitChanged(false, true);
  });
  $('#height').addEventListener('input', (e) => setHeight(+e.target.value, true));
  $('#height').addEventListener('change', (e) => setHeight(+e.target.value, false));
  $('#height').addEventListener('dblclick', () => setHeight(0, false));
  $('#modes').addEventListener('click', (e) => {
    const b = e.target.closest('[data-mode]');
    if (b && b.dataset.mode !== S.mode) setTab('mode', b.dataset.mode);
  });
  $('#subs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-sub]');
    if (b && b.dataset.sub !== sub()) setTab('sub', b.dataset.sub);
  });
  $('#search').addEventListener('input', (e) => { S.q = e.target.value; paintList(); });
  $('#list').addEventListener('toggle', (e) => { if (e.target.matches('details.more')) S.moreOpen = e.target.open; }, true);
  $('#list').addEventListener('click', (e) => {
    const fav = e.target.closest('[data-fav]');
    if (fav) { toggleFav(fav.dataset.fav); return; }
    const del = e.target.closest('[data-del]');
    if (del) { delLook(del); return; }
    const lk = e.target.closest('[data-look]');
    if (lk) { const L = S.looks[+lk.dataset.look]; if (L) { $('#look-name').value = L.name; useLook(L); } return; }
    const mo = e.target.closest('[data-motion]');
    if (mo) { pickMotion(mo.dataset.motion); return; }
    const ft = e.target.closest('[data-fk]');
    if (ft) { setFace(ft.dataset.fk, ft.dataset.fid ? +ft.dataset.fid : null); return; }
    const set = e.target.closest('[data-set]');
    if (set) { wearSet(set.dataset.set); return; }
    const el = e.target.closest('[data-id]');
    if (!el) return;
    const item = S.cat.items.find((i) => i.id === el.dataset.id && i.part === el.dataset.part);
    if (!item) return;
    if (D.worn[item.part] && D.worn[item.part].item.id === item.id) takeOff(item.part);
    else { noteRecent(item); D.wear(item); }
  });
  $('#look-save').addEventListener('click', (e) => {
    const name = lookName();
    const L = cleanLook(currentLook(name), S.cat, FT);
    if (!L) return;
    keepLook(L);
    $('#look-name').value = name;
    paintList();
    flash(e.target, '저장함');
  });
  $('#look-export').addEventListener('click', async (e) => {
    const b = e.target;
    const name = lookName();
    b.disabled = true;
    try {
      const r = await rpc('look_export', name, currentLook(name));
      if (r && r.ok) flash(b, '내보냄', r.file);
      else if (r && r.error) flash(b, '실패', r.error);
    } catch (err) {
      flash(b, '실패', err.message);
    } finally {
      b.disabled = false;
    }
  });
  $('#look-import').addEventListener('click', async (e) => {
    const b = e.target;
    b.disabled = true;
    try {
      const r = await rpc('look_import');
      if (r && r.error) { flash(b, '실패', r.error); return; }
      if (!r || !r.look) return;
      const L = cleanLook({ ...r.look, name: r.look.name || r.file }, S.cat, FT);
      if (!L) { flash(b, '실패', '이 창에 없는 체형입니다'); return; }
      keepLook(L);
      $('#look-name').value = L.name;
      paintList();
      await useLook(L);
    } catch (err) {
      flash(b, '실패', err.message);
    } finally {
      b.disabled = false;
    }
  });
  $('#look-game').addEventListener('click', async (e) => {
    const b = e.target;
    b.disabled = true;
    try {
      const r = await rpc('game_look');
      if (!r || r.error) { showErr(r ? r.error : '게임 캐릭터를 읽지 못했습니다'); return; }
      const L = cleanLook(r.look, S.cat, FT);
      if (!L) { showErr('이 창에 없는 체형입니다'); return; }
      $('#look-name').value = L.name;
      await useLook(L);
      if (r.miss && r.miss.length) showErr('드레스룸에 없어 못 입힌 것: ' + r.miss.join(', '));
      else flash(b, '불러옴', r.at ? r.at + ' 에 본 모습' : '');
    } catch (err) {
      showErr(err.message);
    } finally {
      b.disabled = false;
    }
  });
  $('#front').addEventListener('click', () => stage.front());
  $('#move').addEventListener('click', () => { D.setMove(!D.move); paintActing(); });
  $('#hood').addEventListener('click', () => setCover('hood', !D.hood));
  $('#cap').addEventListener('click', () => setCover('cap', !D.cap));
  $('#weapon').addEventListener('click', () => D.hideWeapon(!D.weaponHide));
  $('#gaze').addEventListener('click', () => setGaze(!S.gaze));
  $('#view-open').addEventListener('click', () => panel.toggle());
  $('#err').addEventListener('click', () => $('#err').classList.add('hidden'));
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && S.full) fullscreen(false); });
}

/** 기억의 탭 값 — 모르는 값은 기본 탭 (없는 동작 갈래는 paintTabs 가 첫 갈래로). */
function restoreTabs(p) {
  const subs = p.subs && typeof p.subs === 'object' ? p.subs : {};
  if (MODES.some(([k]) => k === p.mode)) S.mode = p.mode;
  if (LOOK_SUBS.some(([k]) => k === subs.look)) S.subs.look = subs.look;
  if (WEAR_SUBS.some(([k]) => k === subs.wear)) S.subs.wear = subs.wear;
  if (typeof subs.motion === 'string') S.subs.motion = subs.motion;
}

/** 기억 되살리기 — 쓸 수 있는 값만 (looks.js). 동작·표정·움직임은 기억하지 않는다 (늘 대기 동작으로 연다). */
function restore(p, cat) {
  const obj = (v) => !!v && typeof v === 'object';
  const ids = (a, max) => (Array.isArray(a) ? a.filter((x) => typeof x === 'string') : []).slice(0, max);
  const parts = new Set(cat.parts.map((x) => x.id));
  D.shape = cleanShape(p.shape);
  D.skin = cleanSkin(p.skin);
  D.hood = p.hood === true;
  D.cap = p.cap === true;
  D.weaponHide = p.weaponHide === true;
  restoreTabs(p);
  S.fav = ids(p.fav, FAV_MAX);
  S.recent = ids(p.recent, RECENT_MAX);
  S.gaze = p.gaze !== false;
  S.faces = Object.fromEntries(Object.entries(perBody(p.faces, cat, obj)).map(([b, f]) => [b, cleanFace(f, FT)]));
  S.outfits = Object.fromEntries(Object.entries(perBody(p.outfits, cat, obj)).map(([b, w]) => [b, cleanWorn(w, parts)]));
  S.itemColors = Object.fromEntries(Object.entries(obj(p.itemColors) ? p.itemColors : {})
    .map(([id, c]) => [id, cleanColors(c)]).filter(([, c]) => c).slice(-ITEM_COLORS_MAX));
  S.ages = perBody(p.ages, cat, okAge);
  S.heights = perBody(p.heights, cat, okHeight);
  S.looks = (Array.isArray(p.looks) ? p.looks : []).map((L) => cleanLook(L, cat, FT)).filter(Boolean).slice(-LOOK_MAX);
  S.bundle = obj(p.bundle) ? p.bundle : null;
}

async function main() {
  busy(1);
  const catP = rpc('catalog').catch((e) => ({ error: e.message }));
  const p = (await rpc('prefs').catch(() => null)) || {};
  S.view = cleanView(p.view);
  try {
    stage = new Stage($('#view'), { aa: S.view.aa });
  } catch (e) {
    busy(-1);
    showErr('3D 화면을 만들지 못했습니다 — 그래픽 드라이버를 확인해 주세요', true);
    return;
  }
  stage.onTick = tick;
  backdrop = new Backdrop(stage, modelUrl);
  stage.onLost = () => showErr('그래픽 장치가 끊겼습니다 — 창을 닫고 다시 열어 주세요', true);
  applyView();
  wire();
  paintShapes();
  const cat = await catP;
  busy(-1);
  if (!cat || cat.error) { showErr((cat && cat.error) || '목록을 읽지 못했습니다'); return; }
  S.cat = cat;
  FT = new FaceTable(cat.face);
  MT = new MotionTable(cat.motions);
  Object.assign(D, { ft: FT, bodies: cat.bodies, items: cat.items });
  list.setCatalog(cat);
  cards.setCatalog(cat);
  colorBox.setTable(FT);
  restore(p, cat);
  paintToggles();
  paintShapes();
  await setBody(cat.bodies.some((b) => b.id === p.body) ? p.body : cat.bodies[0].id);
}

main();
