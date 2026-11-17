// 코디 조립 — 화면 없이 체형·얼굴·옷 모델을 불러 공용 뼈대에 붙이고, 몸 조절(셰이프·키)·옷 가림·색·데칼·동작·흔들림을 맞춘다.
// 드레스룸 화면(main.js)과 다른 프로그램이 같이 쓴다. 다른 프로그램 쪽 자료는 성인 체형의 기준 모습만 담아
// 코디에 age 가 없고 몸 조절 자료도 크기·체형만일 수 있다 (body.js) — age 는 드레스룸 화면의 줄 고르기에만 쓴다.
// 받는 것: 모델 주소 함수, 장면(붙이기·떼기), 체형·의상 목록, 얼굴 표(face.js FaceTable). 화면 갱신은 on 알림으로 알린다.
import { Rig, loadModel } from './viewer.js';
import { MESH, DECAL, emptyFace } from './face.js';
import { hideCovered, transferShapes, soleLift } from './fit.js';
import { coverage, gameSlot } from './cover.js';
import { loadClip } from './anim.js';
import { BodyFit } from './body.js';
import { Motion } from './motion.js';
import { Emote } from './emote.js';
import { ClothSet } from './cloth.js';
import { fxTime } from './fx.js';
import { hasMorph } from './facial.js';

export const ONE = ['Top', 'Bottom'];      // 한 벌(OnePiece)과 같이 못 입는 부위
// 장식·무기 — 몸을 가리지 않고 몸 셰이프도 안 옮긴다 (손에 든 부채가 손바닥을 숨기지 않게)
export const DECO = ['FaceDeco', 'EarDeco', 'EyeDeco', 'Weapon'];
// 체형 → 패션 무기 붙는 자세를 고를 (아이?, 성별)
const BODY_KIND = { Female: [false, 'Female'], Male: [false, 'Male'], Girl: [true, 'Female'], Boy: [true, 'Male'] };
const ROLES = ['body', 'head', 'eye', 'beard'];   // base 자리 → 역할 (used() 의 role)
const SKIN = '#F2CBAD';
const HEX = /^#[0-9A-Fa-f]{6}$/;
export const DYE_SLOTS = 6;   // 의상 색 칸 수 (게임 의상은 3색 재질 둘까지)

/** 색 칸 목록 → 대문자 사본 (1~6칸, 칸마다 색 또는 null). 꼴이 틀리면 null. */
export function cleanColors(c) {
  const ok = Array.isArray(c) && c.length >= 1 && c.length <= DYE_SLOTS && c.every((x) => x === null || (typeof x === 'string' && HEX.test(x)));
  return ok ? c.map((x) => x && x.toUpperCase()) : null;
}

export class Dresser {
  /**
   * url(id) → 모델 json 주소 (Promise).
   * scene: { add(model), remove(model) — 떼고 버린다, root(obj, on) — 뼈대 루트를 장면에 넣고 뺀다 }.
   * bodies·items: catalog 의 체형·의상 목록 (코디의 id 로 의상을 찾는다). ft: 얼굴 표 (FaceTable).
   * remembered(item): 색을 안 준 옷의 기억해 둔 색 (없으면 null — 모델 기본색).
   * on: { change(what), error(msg, item), busy(d) } — what: 'body'(체형을 바꾸기 시작) · 'framed'(몸을 세웠다) ·
   *     'worn'(입은 것) · 'cover'(가림 판정) · 'face'(얼굴 색) · 'weapon'(패션 무기 상태·숨김).
   * 매 프레임 부르는 차례: pose(dt) → (시선 등 다른 뼈 고치기) → physics(dt) → effects(dt, camera).
   */
  constructor({ url, scene, bodies = [], items = [], ft, remembered = () => null, on = {} }) {
    this.url = url;
    this.scene = scene;
    this.bodies = bodies;
    this.items = items;
    this.ft = ft;
    this.remembered = remembered;
    this.on = { change() {}, error() {}, busy() {}, ...on };
    this.cloth = new ClothSet();   // 옷·머리 흔들림 (cloth.js) — physics(dt) 가 돌린다, 바깥 팀은 cloth.add(자료, rig)
    this.body = null;
    this.shape = '';
    this.skin = null;          // 고른 피부색 (null = 몸 모델 기본)
    this.skinBase = SKIN;
    this.face = emptyFace();   // 지금 체형의 얼굴 고른 값 (부르는 쪽 기억과 같은 객체여도 된다)
    this.age = null;           // 화면의 몸 조절 줄 고르기 값 (null = 기준, 묶음 자료엔 없다)
    this.height = 0;           // 키 조절값 (-1..1)
    this.hood = false;         // 후드 쓰기
    this.cap = false;          // 투구 덮개 닫기
    this.weapon = 'Undrawn';   // 패션 무기 'Drawn'(손에)·'Undrawn'(넣음) — 동작이 정한다 (fitWeapon)
    this.weaponHide = false;   // 패션 무기 숨김
    this.stepsWeapon = 'Undrawn';   // 고른 동작이 무기를 든 동작이면 'Drawn' (play 의 weapon — MotionTable.weapon)
    this.cover = null;         // 마지막 가림 판정 (cover.js coverage)
    this.rig = null;           // 공용 뼈대 (체형마다 새로)
    this.fit = null;           // 몸 조절 (셰이프·키 — 자료가 없으면 null)
    this.ready = null;         // 몸이 뼈대를 세운 뒤 풀리는 약속 — 다른 모델은 그 뒤에 뼈를 붙인다
    this.base = [];            // 몸·머리·눈·수염 모델 (face.js MESH 자리, 수염은 없을 수 있다)
    this.worn = {};            // 부위 → {item, colors, model}
    this.pending = null;       // 체형을 세우는 동안 {rig, outfit} — 그 체형에 입힐 코디
    this.move = true;          // 동작을 튼다 (끄면 기본 자세)
    this.clip = null;          // 지금 동작 (motion.js Motion)
    this.clipT0 = 0;           // 그 동작을 시작한 time
    this.time = 0;
    this.playing = null;       // 지금 동작 열쇠 (play)
    this.steps = null;         // 고른 동작 단계 (없으면 대기 동작)
    this.tl = [];              // 단계마다 감정 표현 이펙트·소품 (emote.js Emote — 없으면 null)
    this.tlClock = [-1, 0];    // 이번 프레임 [동작 단계, 단계 시간] (pose 가 정하고 effects 가 쓴다)
    this.expr = null;          // 고른 표정 클립 (anim.js Clip — 얼굴 뼈만, 동작 위에 반복)
    this.exprStem = null;      // 그 표정 줄기 (setExpr)
    this.exprT0 = 0;
    this.faceVals = new Map(); // 이번 프레임 표정 키 (동작의 표정 짝 → 고른 표정 순으로 덮는다 — facial.js)
    this.faceBlinks = false;   // 표정 키가 눈꺼풀을 움직이나 (그동안 저절로 깜빡이기는 쉰다)
    this.decals = new Map();   // 데칼 부품 모델 → 그림 주소
    this.bodyDecal = null;     // 지금 몸 문신 데칼 값 (Model.setDecal 'body') — 옷의 피부 조각에도 얹는다
  }

  // ── 모델 ──
  models() {
    return [...this.base.filter(Boolean), ...this.wornModels()];
  }

  wornModels() {
    return Object.values(this.worn).map((w) => w.model).filter(Boolean);
  }

  /** 몸이 아닌 모델 — 몸 뼈대가 선 다음 붙인다. 기다리는 사이 체형이 바뀌면 버린다 (새 뼈대에 옛 체형 뼈를 꽂지 않게). */
  async fetchModel(id) {
    const rig = this.rig;
    const url = await this.url(id);
    await this.ready;
    if (rig !== this.rig) throw new Error('체형이 바뀌었습니다');
    return loadModel(id, url, rig);
  }

  applyLook(m) {
    m.setShape(this.shape);
    m.setSkin(this.skin || this.skinBase);
    m.setMorph('Adolescent', this.fit && this.fit.state ? this.fit.state.adolescent : 0);
  }

  /** 체형 폴더 (Female·Male·Infant). */
  folder() {
    const b = this.bodies.find((x) => x.id === this.body);
    return b ? b.folder : '';
  }

  /** 지금 체형이 입을 수 있는 품목인가 — 체형 폴더가 같거나 체형 공용(폴더 '', 패션 무기). */
  fits(i) {
    return !i.folder || i.folder === this.folder();
  }

  // ── 몸 ──
  /** 기본 자세 + 몸 조절 위치 (행렬 갱신까지). 옷 맞추기·키 재기는 이 자세에서 한다. */
  restPose() {
    this.rig.rest(false);
    if (this.fit) this.fit.apply();
    this.rig.root.updateMatrixWorld(true);
  }

  /** 옷에 덮인 몸을 숨기고, 굽 있는 신발이면 그만큼 띄운다 (입고 벗거나 체형을 바꿀 때마다 — 기본 자세에서 잰다). */
  refit() {
    if (!this.base[0]) return;
    const shoes = this.worn.Shoes && this.worn.Shoes.model;
    this.rig.root.position.y = 0;
    this.restPose();
    if (shoes) {
      this.rig.root.position.y = soleLift(shoes);
      this.restPose();
    }
    hideCovered(this.base[0], Object.entries(this.worn).filter(([p, w]) => w.model && w.model.shown && !DECO.includes(p)).map(([, w]) => w.model));
  }

  /** 지금 나이·셰이프·키를 뼈대에 (모델 스킨까지). */
  applyFit() {
    if (!this.fit) return;
    this.fit.set(this.age, this.shape || 'Default', this.height || 0);
    this.fit.skin(this.models().flatMap((m) => m.meshes));
    for (const m of this.models()) m.setMorph('Adolescent', this.fit.state.adolescent);
  }

  setShape(shape) {
    this.shape = shape;
    for (const m of this.models()) m.setShape(shape);
    this.applyFit();
    this.refit();
  }

  setSkin(hex) {
    this.skin = hex;
    for (const m of this.models()) m.setSkin(hex || this.skinBase);
  }

  /** 나이·키 자료 (없거나 못 읽으면 null — 나이·키 없이 기본 몸으로). */
  async loadBdc(body) {
    try {
      return await (await fetch(await this.url('bdc:' + body))).json();
    } catch (e) {
      return null;
    }
  }

  /**
   * 체형을 바꾸고 코디를 입힌다 — worn {부위: {id, colors}}, face (얼굴 고른 값), age·height (나이·키).
   * worn 이 비고 starter 면 머리 하나는 얹는다. 목록에 없어 못 입힌 옷 수를 돌려준다.
   * 옷은 기다리지 않는다 (입는 중인 옷도 worn 에 칸은 있다).
   */
  async setBody(body, { worn = {}, face = emptyFace(), age = null, height = 0, starter = false } = {}) {
    for (const p of Object.keys(this.worn)) this.drop(p);   // 버릴 몸이라 가림·몸 맞추기는 다시 안 한다
    for (const m of this.base) if (m) this.scene.remove(m);
    if (this.rig) this.scene.root(this.rig.root, false);
    this.base = [];
    this.cover = null;
    this.clip = null;
    this.setTimelines([]);
    this.fit = null;
    this.body = body;
    this.face = face;
    this.age = age;
    this.height = height;
    const rig = (this.rig = new Rig());
    this.bodyDecal = null;   // 새 체형의 문신은 faceDecals 가 다시 정한다 (체형마다 몸 UV 가 다르다)
    this.pending = { rig, outfit: worn };
    this.scene.root(rig.root, true);
    let ready;
    this.ready = new Promise((r) => { ready = r; });
    this.on.change('body');
    this.on.busy(1);
    try {
      const b = await loadModel('body:' + body, await this.url('body:' + body), rig);
      if (this.rig !== rig) { b.dispose(); return 0; }
      this.base = [b];
      ready();
      const [h, e, bdc] = await Promise.all([this.fetchModel(this.meshId('heads')), this.fetchModel(this.meshId('eyes')), this.loadBdc(body)]);
      if (this.rig !== rig) { h.dispose(); e.dispose(); return 0; }
      const skin = b.mats.find((x) => x.userData.info.skin && x.userData.info.kind === 'dye');
      this.skinBase = skin ? skin.userData.info.dye[0] : SKIN;
      this.base = [b, h, e];
      b.pushBack();
      if (bdc) {
        this.fit = new BodyFit(rig, bdc);
        if (this.age == null) this.age = bdc.base_age ?? null;
        this.applyFit();
      }
      for (const m of this.base) { this.applyLook(m); this.scene.add(m); }
      this.refit();
      this.on.change('framed');
      this.dressFace();
    } catch (err) {
      this.on.error(err.message);
    } finally {
      ready();
      this.on.busy(-1);
    }
    let miss = 0;
    if (Object.keys(worn).length) {
      for (const [part, w] of Object.entries(worn)) {
        if (this.worn[part]) continue;   // 몸을 불러오는 사이에 고른 옷이 먼저
        const item = this.items.find((i) => i.id === w.id && i.part === part);
        if (item) this.wear(item, w.colors); else miss++;
      }
    } else if (starter) {
      const hair = this.items.find((i) => i.part === 'Hair' && this.fits(i));
      if (hair) this.wear(hair);   // 처음 보는 체형은 머리 하나는 얹어 둔다
    }
    if (this.pending && this.pending.rig === rig) this.pending = null;   // 이제 worn 이 코디다
    return miss;
  }

  /** 코디 하나를 통째로 (체형·셰이프·나이·키·피부·얼굴·옷 — 화면 currentLook 꼴). 못 입힌 옷 수. */
  dress(look) {
    this.shape = look.shape || '';
    this.skin = look.skin || null;
    return this.setBody(look.body, { worn: look.worn || {}, face: { ...emptyFace(), ...(look.face || {}) },
      age: Number.isInteger(look.age) ? look.age : null, height: look.height || 0 });
  }

  // ── 가림 ──
  /** 입은 옷끼리 가리는 것 (cover.js) — 부위 숨김·머리 단계·후드 모양·가린 눈. 입고 벗거나 후드·덮개를 바꿀 때마다. */
  applyCover() {
    const worn = Object.entries(this.worn).filter(([, w]) => w.model);
    const c = coverage(worn.map(([p, w]) => ({ slot: gameSlot(p, w.model.fit), rules: w.model.rules, hoods: w.model.hoods(), cover: w.model.cover() })),
      { hood: this.hood, cap: this.cap });
    for (const [i, [p, w]] of worn.entries()) {
      w.model.setShown(c.shown[i]);
      w.model.setHood(c.hood);
      if (p === 'Hair') w.model.setHairCover(c.hair);
    }
    const head = this.base[MESH.heads], eye = this.base[MESH.eyes], beard = this.base[MESH.beards];
    if (head) { head.setShown(!c.hidden.has('Head')); head.setMouth(c.mouth); }
    if (beard) beard.setShown(!c.hidden.has('Beard'));
    if (eye) { eye.setShown(!c.hidden.has('Eye')); eye.setEyeHide(c.hidden); }
    this.cover = c;
    this.on.change('cover');
  }

  /** 후드 쓰기 · 투구 덮개 닫기 (key 'hood' | 'cap'). */
  setCover(key, on) {
    this[key] = on;
    this.applyCover();
    this.refit();
  }

  // ── 패션 무기 ──
  /** 무기 상태('Drawn'·'Undrawn', null = 무기마다 구운 기본)와 숨김. 넣으면 붙는 소켓이 바뀔 수 있어 자세를 다시 놓는다.
   *  보통은 동작이 정하므로(fitWeapon) 바깥에서는 숨김만 바꾼다 (hideWeapon). */
  setWeapon(state = this.weapon, hide = this.weaponHide) {
    this.weapon = state === 'Drawn' || state === 'Undrawn' ? state : null;
    this.weaponHide = !!hide;
    const m = this.worn.Weapon && this.worn.Weapon.model;
    if (m && m.hasTools) {
      this.fitTools(m);
      this.restPose();
      this.cloth.reset([m]);   // 뿌리가 손 ↔ 등으로 옮겨 가 술 같은 흔들림이 튀지 않게 처음부터
    }
    this.on.change('weapon');
  }

  hideWeapon(on) {
    this.setWeapon(this.weapon, on);
  }

  /** 무기를 지금 동작에 맞춘다 — 무기를 든 동작(play 의 weapon 'Drawn')을 틀고 있으면 손에, 그 밖(대기·움직임 끔·못 불러옴)은 넣은 모습. */
  fitWeapon() {
    const st = this.acting ? this.stepsWeapon : 'Undrawn';
    if (st !== this.weapon) this.setWeapon(st);
  }

  /** 모델의 패션 무기 도구를 지금 상태·숨김으로, 체형에 맞는 소켓 자세에 놓는다 (무기가 아니면 붙는 곳만). */
  fitTools(m) {
    if (m.hasTools) m.setTool(this.weapon, this.weaponHide);
    m.poseTools(this.rig, ...(BODY_KIND[this.body] || BODY_KIND.Female));
  }

  // ── 얼굴 ──
  /** 얼굴 메시 모델 id — 고른 것이 없거나 이 체형에 없으면 체형 기본 (수염은 null). */
  meshId(kind) {
    const m = this.ft.model(kind, this.face, this.body);
    if (m) return 'face:' + m;
    return kind === 'heads' ? 'head:' + this.body : kind === 'eyes' ? 'eye:' + this.body : null;
  }

  /** 투톤 머리인가 — 모델 정의에서 두 번째 머리 칸(Hair1)에 이어진 염색 채널이 있는 머리만 두 색을 받는다. */
  twoTone(id) {
    const p = this.ft.part(id);
    return !!(p && p.ch && p.ch.includes('Hair1'));
  }

  /** 입은 머리의 염색 칸 [[칸 번호, 칸 이름]] — 부품 값(ch)이 없으면 세 칸을 번호로. */
  hairSlots(w) {
    const p = this.ft.part(w.item.id);
    if (!p || !p.ch) return w.colors.map((_, i) => [i, null]);
    return p.ch.map((name, i) => [i, name]).filter(([i, name]) => name && i < w.colors.length);
  }

  /** 머리색 — 입은 머리의 'Hair' 칸 (게임은 눈썹·수염에 머리색을 넣는다). 칸 이름은 머리마다 자리가 달라
   *  hairSlots 로 찾고, 이름이 없는 머리만 칸 1. */
  hairColor() {
    const w = this.worn.Hair;
    if (!w || !w.colors) return null;
    const hit = this.hairSlots(w).find(([, name]) => name === 'Hair');
    return w.colors[hit ? hit[0] : 0] || null;
  }

  /** 머리를 바꿀 때 전 머리 색을 칸 이름(Hair·Hair1·HairAccessory)대로 옮긴다 — 전 머리에 없던 Hair1 은 Hair 색. */
  carryHair(prev, item) {
    if (!prev || !prev.colors) return null;
    const named = {};
    for (const [i, name] of this.hairSlots(prev)) if (prev.colors[i]) named[name || (i ? null : 'Hair')] = prev.colors[i];
    const p = this.ft.part(item.id);
    const out = ((p && p.ch) || ['Hair', null, null]).map((name) => (name && (named[name] || (name === 'Hair1' ? named.Hair : null))) || null);
    return out.some(Boolean) ? out : null;
  }

  /** 체형을 세운 뒤 — 수염·데칼·색. */
  dressFace() {
    if (this.meshId('beards')) this.swapMesh('beards');
    this.faceDecals();
    this.faceColors();
  }

  /** 얼굴형·눈·수염 메시를 고른 것으로 바꾼다. */
  async swapMesh(kind) {
    const i = MESH[kind], id = this.meshId(kind), rig = this.rig, old = this.base[i];
    if ((old ? old.id : null) === id) return;
    this.on.busy(1);
    try {
      const m = id ? await this.fetchModel(id) : null;
      if (this.rig !== rig || this.meshId(kind) !== id) { if (m) m.dispose(); return; }
      if (this.base[i]) this.scene.remove(this.base[i]);
      this.base[i] = m || undefined;
      if (m) {
        if (this.fit) { this.fit.build(); this.fit.skin(m.meshes); }
        this.applyLook(m);
        this.scene.add(m);
      }
      this.applyCover();   // 새 얼굴·눈·수염도 옷이 가리던 대로
      if (kind === 'heads') await this.faceDecals();
      this.faceColors();
    } catch (err) {
      this.on.error(err.message);
    } finally {
      this.on.busy(-1);
    }
  }

  async decalUrl(name) {
    if (!this.decals.has(name)) {
      const url = await this.url('decal:' + name);
      const meta = await (await fetch(url)).json();
      this.decals.set(name, url.slice(0, url.lastIndexOf('/') + 1) + '../tex/' + meta.tex + '.png');
    }
    return this.decals.get(name);
  }

  /** 입·문신 데칼을 지금 얼굴·몸에 얹는다 (고른 것이 없으면 뗀다 — 입은 표정 표의 기본 입으로). */
  async faceDecals() {
    const f = this.face, body = this.body, rig = this.rig;
    const seq = (this.decalSeq = (this.decalSeq || 0) + 1);
    for (const [kind, where] of Object.entries(DECAL)) {
      const name = this.ft.model(kind, f, body);
      let d = null;
      if (name) {
        const p = this.ft.part(name);
        try {
          d = { url: await this.decalUrl(name), st: p.st, rot: p.rot, dye: p.dye, scar: /Scar$/.test(p.slot || ''), color: f.tat };
        } catch (err) {
          this.on.error(err.message);
        }
      }
      if (this.rig !== rig || this.decalSeq !== seq) return;
      if (where === 'body') {   // 가슴이 드러나는 옷은 그 살을 옷의 피부 조각이 그린다 — 몸과 같은 UV 라 같은 데칼을 얹는다
        this.bodyDecal = d;
        for (const m of [this.base[0], ...this.wornModels()]) if (m) m.setDecal('body', d);
        continue;
      }
      const head = this.base[MESH.heads];
      if (head) head.setDecal(where, d);
    }
  }

  /** 얼굴 색 — 눈동자·눈썹·수염 (눈썹·수염은 머리색을 따른다). */
  faceColors() {
    const f = this.face, eye = this.base[MESH.eyes], beard = this.base[MESH.beards], hair = this.hairColor();
    if (eye) { eye.setEyeColor(f.eye); eye.setBrow(hair); }
    if (beard) beard.setDyes(hair ? [hair] : beard.defaults() || []);
    this.on.change('face');
  }

  /** 문신 색 (null = 그림 그대로). */
  setTat(hex) {
    this.face.tat = hex;
    if (this.bodyDecal) this.bodyDecal = { ...this.bodyDecal, color: hex };
    const head = this.base[MESH.heads];
    if (head) head.setDecalColor('face', hex);
    for (const m of [this.base[0], ...this.wornModels()]) if (m) m.setDecalColor('body', hex);
  }

  // ── 입기·벗기 ──
  /** 입는다 — 색을 안 주면 머리는 전 머리 색을 잇고, 옷은 기억해 둔 색 (remembered). 다 입으면 true. */
  async wear(item, colors) {
    const part = item.part;
    const given = cleanColors(colors) || (part === 'Hair' ? this.carryHair(this.worn.Hair, item) : cleanColors(this.remembered(item)));
    const off = part === 'OnePiece' ? ONE : ONE.includes(part) ? ['OnePiece'] : [];
    for (const p of off) this.takeOff(p);
    this.takeOff(part);
    const slot = { item, colors: given, model: null };
    this.worn[part] = slot;
    this.on.change('worn');
    this.on.busy(1);
    let ok = false;
    try {
      const m = await this.fetchModel(item.id);
      if (this.worn[part] !== slot) { m.dispose(); return false; }
      slot.model = m;
      this.fitTools(m);
      m.pushBack(1, true);   // 옷의 피부 조각 — 몸보다 앞, 옷 천보다 뒤
      // 칸 수는 모델 것 (옛 3칸 코디·게임의 6칸 색도 맞춘다)
      slot.colors = (this.defaultColors(slot) || []).map((d, i) => (slot.colors && slot.colors[i]) || d);
      m.setDyes(slot.colors);
      if (this.fit) { this.fit.build(); this.fit.skin(m.meshes); }   // 옷이 보탠 뼈까지 다시 잰다
      if (this.base[0]) { this.restPose(); if (!DECO.includes(part)) transferShapes(this.base[0], m); }
      this.applyLook(m);
      if (this.bodyDecal) m.setDecal('body', this.bodyDecal);   // 옷의 피부 조각에도 몸 문신
      this.scene.add(m);
      this.applyCover();
      this.refit();
      if (part === 'Hair') this.faceColors();
      ok = true;
    } catch (e) {
      if (this.worn[part] === slot) {
        delete this.worn[part];
        this.on.error(e.message, item);
      }
    } finally {
      this.on.busy(-1);
    }
    this.on.change('worn');
    return ok;
  }

  /** 입은 것 하나를 떼기만 한다 (가림·몸 맞추기·얼굴 색은 부르는 쪽이). 뗀 칸 또는 null. */
  drop(part) {
    const w = this.worn[part];
    if (!w) return null;
    delete this.worn[part];
    if (w.model) this.scene.remove(w.model);
    return w;
  }

  /** 벗는다. 입고 있었으면 true. */
  takeOff(part) {
    if (!this.drop(part)) return false;
    this.applyCover();
    this.refit();
    if (part === 'Hair') this.faceColors();
    return true;
  }

  /** 입은 옷 w 의 칸마다 기본색 — 게임 시트의 아이템 기본 염색(DyeColor0~5)이 먼저, 시트에 없는 칸은 재질 기본색.
   *  칸 수는 모델 것. 받는 칸이 없거나 아직 못 불렀으면 null (염색 불가). */
  defaultColors(w) {
    const md = w && w.model ? w.model.defaults() : null;
    if (!md) return null;
    const sheet = (w.item && w.item.colors) || [];
    return md.map((d, i) => sheet[i] || d);
  }

  /** 옷 색 칸 i 를 바꾼다 (머리면 눈썹·수염도). */
  setDye(part, i, hex) {
    const w = this.worn[part];
    if (!w || !w.model) return null;
    w.colors[i] = hex.toUpperCase();
    w.model.setDyes(w.colors);
    if (part === 'Hair') this.faceColors();
    return w;
  }

  /** 옷 색을 통째로 (기본색으로 돌리기 등). */
  setDyes(part, colors) {
    const w = this.worn[part];
    if (!w || !w.model) return null;
    w.colors = colors;
    w.model.setDyes(colors);
    if (part === 'Hair') this.faceColors();
    return w;
  }

  // ── 동작 ──
  /** 동작을 튼다 — steps [{body, face}] (motion.js MotionTable.steps), 없으면 꾸미기 화면 대기 동작.
   *  weapon: 그 동작의 무기 상태 (MotionTable.weapon — 'Drawn' 이면 무기를 손에, 다 불러온 뒤 fitWeapon 이 맞춘다).
   *  같은 동작이 이미 돌고 있으면 그대로 둔다. 고른 동작을 못 불러오면 예외 (대기 동작은 조용히 없이). */
  async play(steps = null, weapon = 'Undrawn') {
    const want = steps ? JSON.stringify(steps) : 'anim:' + this.body + ':' + this.shape;
    if (this.playing === want && this.clip) return;
    this.playing = want;
    this.steps = steps;
    this.stepsWeapon = steps && weapon === 'Drawn' ? 'Drawn' : 'Undrawn';
    const rig = this.rig;
    let tl = [];
    try {
      const fx = steps ? this.loadTimelines(steps, rig) : [];
      const m = steps ? await Motion.load(steps, (stem) => this.url('clip:' + stem))
        : new Motion([{ clip: await loadClip(await this.url(want)), face: null }]);
      tl = await fx;
      if (this.playing === want) {
        this.clip = m;
        this.clipT0 = this.time;
        if (this.rig === rig) {   // 기다리는 사이 체형이 바뀌면 소품 뼈가 옛 뼈대에 있다 — 이펙트 없이
          this.setTimelines(tl);
          tl = [];
        }
      }
    } catch (e) {
      if (this.playing !== want) return;
      this.clip = null;
      this.setTimelines([]);
      if (steps) throw e;
    } finally {
      for (const x of tl) if (x) x.dispose();   // 기다리는 사이 다른 동작을 골랐다
      if (this.playing === want) this.fitWeapon();
    }
  }

  /** 단계마다 감정 표현 이펙트·소품 (없거나 못 불러오면 null — 덤이라 동작은 튼다). 소품 뼈는 rig 에. */
  loadTimelines(steps, rig) {
    return Promise.all(steps.map(async (s) => {
      if (!s.tl || !rig) return null;
      try {
        return await Emote.load(s.tl, (id) => this.url(id), rig, this.folder());
      } catch (e) {
        console.warn('감정 표현 이펙트를 불러오지 못했습니다', s.tl, e);
        return null;
      }
    }));
  }

  /** 지금 동작의 감정 표현 이펙트·소품을 바꾼다 (전 것은 장면에서 빼고 놓는다). */
  setTimelines(list) {
    for (const e of this.tl) {
      if (!e || list.includes(e)) continue;
      for (const m of e.models()) this.scene.remove(m);
      e.dispose();
    }
    this.tl = list;
    for (const e of list) if (e) for (const m of e.models()) this.scene.add(m);
  }

  /** 동작 틀기 켜고 끄기 (끄면 기본 자세 — 무기도 넣는다). */
  setMove(on) {
    this.move = !!on;
    this.fitWeapon();
  }

  /** 표정을 얹는다 — 표정 줄기 (null = 끈다). 같은 것이면 그대로, 기다리는 사이 바뀌면 버린다. 못 불러오면 예외. */
  async setExpr(stem) {
    if (stem === this.exprStem) return;
    this.exprStem = stem || null;
    this.expr = null;
    if (!stem) return;
    try {
      const c = await loadClip(await this.url('clip:' + stem));
      if (this.exprStem === stem) { this.expr = c; this.exprT0 = this.time; }
    } catch (e) {
      if (this.exprStem === stem) this.exprStem = null;   // 다음에 다시 고르면 다시 불러온다
      throw e;
    }
  }

  /** 매 프레임 — 기본 자세 → 동작 → 표정 → 몸 조절, 표정 키를 얼굴에. 시선·깜빡임(life.js)은 부르는 쪽이 그 뒤에
   *  (표정 키가 눈꺼풀을 움직이면 faceBlinks — 깜빡이기를 쉬게 한다). */
  pose(dt) {
    if (!this.rig) return;
    this.time += dt;
    this.rig.rest(false);
    const vals = this.faceVals;
    vals.clear();
    let face = false;
    this.tlClock = [-1, 0];
    if (this.move && this.clip) {
      const t = this.time - this.clipT0;
      this.clip.apply(this.rig, t);
      face = this.clip.faceKeys(t, vals);
      if (this.clip.picked && this.tl.length) this.tlClock = this.clip.clock(t);
    }
    if (this.tl.length) {   // 감정 표현 소품 — 지금 단계 것만 그 단계 시간으로
      const [step, t] = this.tlClock;
      this.tl.forEach((e, i) => { if (e) e.pose(this.rig, i === step ? t : null); });
    }
    if (this.expr) {   // 동작의 표정 짝보다 위
      const t = this.time - this.exprT0;
      this.expr.apply(this.rig, t);
      if (this.expr.keys) {
        this.expr.keys.sample(t, true, vals);
        face = true;
      }
    }
    if (this.fit) this.fit.apply();
    if (this.tl.length) {   // 감정 표현 손 IK — 몸 크기까지 맞춘 자세에서 소품을 입에
      const [step, t] = this.tlClock;
      const e = this.tl[step];
      if (e) e.reach(this.rig, t);
    }
    for (const m of this.base) if (m) m.setFace(face ? vals : null);
    this.faceBlinks = face && hasMorph(vals);
  }

  /** 흔들림 한 걸음 — pose 뒤 시선·다른 뼈 고치기까지 다 끝난 다음 부른다 (cloth.js). 흔든 팀 수.
   *  흔드는 뼈의 로컬 자세를 바꾸므로 다음 프레임 pose 의 기본 자세(rig.rest)로 돌아간다. */
  physics(dt) {
    if (!this.rig) return 0;
    return this.cloth.update(dt, this.rig, this.models());
  }

  /** 의상·감정 표현 이펙트 한 걸음 — 자세·시선·흔들림까지 다 고친 뒤 부른다 (파티클 자리를 이번 프레임 뼈 행렬로 잡는다).
   *  감정 표현 이펙트는 동작의 지금 단계 것만 그 단계 시간으로 (동작을 끄면 멈춘다). */
  effects(dt, camera) {
    const tl = this.tl.some(Boolean);
    if (!this.rig || !camera || (!tl && !this.wornModels().some((m) => m.fx))) return;
    this.rig.root.updateMatrixWorld(true);
    camera.updateMatrixWorld();
    fxTime.value = this.time % 1000;
    if (tl) {
      const [step, t] = this.tlClock;
      this.tl.forEach((e, i) => { if (e) e.effects(dt, this.rig, camera, i === step ? t : null); });
    }
    for (const m of this.wornModels()) {
      if (!m.fx) continue;
      try {
        m.fx.update(dt, this.rig, camera);
      } catch (e) {   // 이펙트 하나가 틀려도 화면은 계속 돈다 — 그 이펙트만 끈다
        console.warn('의상 이펙트를 끕니다', m.id, e);
        m.fx.dispose();
        m.fx = null;
      }
    }
  }

  /** 고른 동작을 틀고 있나 (대기 동작이 아니라) — 그동안 시선은 쉰다.
   *  표정은 눈알 회전을 기본값으로만 두므로(시선이 돌리는 뼈) 표정 중에도 시선은 그대로. */
  get acting() {
    return !!(this.move && this.clip && this.clip.picked);
  }
  /** 무기를 들었나 (붙는 곳이 있는 패션 무기 모델을 다 불렀다). */
  get hasWeapon() {
    const m = this.worn.Weapon && this.worn.Weapon.model;
    return !!(m && m.hasTools);
  }

  /** 지금 모습에 쓰인 모델 [{id, role, …}] — 다른 프로그램이 이 모습을 다시 꺼낼 때 쓴다 (main.js 기억 bundle). 동작 클립은 뺀다. */
  used() {
    const out = [];
    const add = (id, role, extra = {}) => { if (id && !out.some((x) => x.id === id)) out.push({ id, role, ...extra }); };
    ROLES.forEach((role, i) => { if (this.base[i]) add(this.base[i].id, role); });
    if (this.fit) add('bdc:' + this.body, 'bdc');
    for (const [kind, where] of Object.entries(DECAL)) {
      const name = this.ft.model(kind, this.face, this.body);
      if (name) add('decal:' + name, 'decal', { kind, where });
    }
    for (const [part, w] of Object.entries(this.worn)) if (w.model) add(w.item.id, 'item', { part });
    return out;
  }
}
