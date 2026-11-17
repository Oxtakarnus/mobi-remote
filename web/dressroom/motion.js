// 동작 탭 — 동작 목록(mabi/dress/motions.py 표)과 재생 순서.
// 한 동작은 단계 여럿(시작 → 반복)이다. 앞 단계는 한 번씩, 마지막 단계는 반복한다.
// 단계마다 표정 클립(얼굴 뼈만)이 있으면 같은 시간에 얹는다.
// 표정 갈래(face)는 몸 동작이 아니라 얼굴 클립 하나 — 지금 동작 위에 따로 얹는다 (Dresser.setExpr).
import { loadClip } from './anim.js';

export class MotionTable {
  /** t: catalog 의 motions ({cats, list, facial}) — 없으면 동작 탭을 숨긴다. */
  constructor(t) {
    this.t = t && Array.isArray(t.list) ? t : null;
    this.byId = new Map((this.t ? this.t.list : []).map((e) => [e.id, e]));
  }

  get ok() {
    return !!this.t;
  }

  /** 갈래 [[id, 이름]]. */
  cats() {
    return this.t ? this.t.cats.map((c) => [c.id, c.name]) : [];
  }

  catName(id) {
    const c = this.t && this.t.cats.find((x) => x.id === id);
    return c ? c.name : '';
  }

  /** 이 체형 폴더에서 틀 수 있는 동작 — 갈래 cat (null 이면 전부), 이름에 q 가 든 것. */
  list(cat, folder, q = '') {
    if (!this.t) return [];
    return this.t.list.filter((e) => (!cat || e.cat === cat) && e.steps[folder] && (!q || e.name.toLowerCase().includes(q)));
  }

  has(id, folder) {
    const e = this.byId.get(id);
    return !!(e && e.steps[folder]);
  }

  /** 표정 갈래 것인가. */
  isFace(id) {
    const e = this.byId.get(id);
    return !!e && e.cat === 'face';
  }

  /** 표정 id → 이 체형 폴더의 표정 줄기 (없으면 null). */
  faceStem(id, folder) {
    const e = this.isFace(id) && this.byId.get(id).steps[folder];
    return (e && e[''] && e[''][0]) || null;
  }

  /** 이 동작에서 패션 무기 상태 (Dresser.play 의 weapon) — 무기를 꺼내 드는 전투 동작(표의 drawn — 게임 시트에
   *  직업별 갈래가 있는 상태)이면 'Drawn', 그 밖(고르지 않음·대기·감정 표현·꾸미기 포함)은 넣은 모습 'Undrawn'. */
  weapon(id) {
    const e = id ? this.byId.get(id) : null;
    return e && e.drawn ? 'Drawn' : 'Undrawn';
  }

  /** 동작 id → 단계 [{body: 줄기, face: 표정 줄기 | null, tl: 이펙트 타임라인 | null}] (그 셰이프 것이 없으면 기본).
   *  없거나 표정이면 null.
   *  job: 입은 패션 무기의 직업 (목록 항목 job) — 그 직업 갈래(표의 jobs)가 이 체형에 있으면 그 동작. */
  steps(id, folder, shape, job = '') {
    const e = this.byId.get(id);
    if (!e || e.cat === 'face' || !e.steps[folder]) return null;
    const s = (job && e.jobs && e.jobs[job] && e.jobs[job][folder]) || e.steps[folder];
    const tl = this.t.timeline || {};
    return (s[shape] || s['']).map((stem) => ({ body: stem, face: this.t.facial[stem] || null, tl: tl[stem] || null }));
  }

  /** 무기 직업마다 다른 동작인가 — 무기를 바꾸면 다시 고른다. */
  byJob(id) {
    const e = id ? this.byId.get(id) : null;
    return !!(e && e.jobs);
  }
}

export class Motion {
  /** steps: [{clip, face}] · picked: 동작 탭에서 고른 것 (아니면 대기 동작). */
  constructor(steps, picked = false) {
    this.steps = steps;
    this.picked = picked;
  }

  /** 단계 [{body, face}] → 클립을 불러 만든다. url(줄기) → 모델 주소. 표정은 덤이라 못 불러도 몸 동작은 튼다. */
  static async load(steps, url) {
    const one = async (stem) => loadClip(await url(stem));
    const out = await Promise.all(steps.map(async (s) => {
      const [clip, face] = await Promise.all([one(s.body), s.face ? one(s.face).catch(() => null) : null]);
      return { clip, face };
    }));
    return new Motion(out, true);
  }

  /** 동작 시작부터 time(초) → [그 단계, 단계 안 시간, 반복?] — 마지막 단계만 반복한다 (반복 단계의 시간은 바퀴를 안 접는다). */
  at(time) {
    let t = Math.max(0, time);
    const n = this.steps.length;
    for (let i = 0; i < n - 1; i++) {
      const s = this.steps[i];
      if (t < s.clip.length) return [s, t, false];
      t -= s.clip.length;
    }
    return [this.steps[n - 1], t, true];
  }

  /** 동작 시작부터 time(초) 지난 자세를 뼈대에. */
  apply(rig, time) {
    const [s, t, loop] = this.at(time);
    s.clip.apply(rig, t, loop);
    if (s.face) s.face.apply(rig, t, loop);
  }

  /** 그 시간의 [단계 번호, 이번 바퀴 안 시간] — 단계마다 따로 도는 이펙트(타임라인)용. 반복 단계는 바퀴마다 0 부터. */
  clock(time) {
    const [s, t, loop] = this.at(time);
    const len = s.clip.length;
    return [this.steps.indexOf(s), loop && len > 0 ? t % len : t];
  }

  /** 그 시간 표정 짝의 표정 키를 out(Map)에 — 넣었으면 true. */
  faceKeys(time, out) {
    const [s, t, loop] = this.at(time);
    if (!s.face || !s.face.keys) return false;
    s.face.keys.sample(t, loop, out);
    return true;
  }
}
