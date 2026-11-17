// 감정 표현 타임라인 한 단계 — 이펙트(fx)·소품(prop)·손 IK. 모델 id 'tl:<타임라인>' ({fx, props, ik, sockets},
// mabi/dress/service.py). 소품은 몸 뼈 밑에 붙는 모델('tlp:' — 패션 무기처럼 뼈대에 소품 뼈를 더한다)과 소품 동작('tlc:' —
// 소품 루트 기준 경로라 뼈대에 놓을 땐 소품 루트 경로를 앞에 붙인다). sockets 는 기본 머리에 없는 입 이펙트 소켓 같은
// 노드 (체형 폴더마다 — 얼굴형 모델에 이미 있으면 그대로 둔다). 동작의 그 단계 시간(motion.js clock)으로 구간 안에서만 돈다.
import * as THREE from './vendor/three.module.min.js';
import { Model, loadModel, fxTexture } from './viewer.js';
import { FxPlayer } from './fx.js';
import { loadClip } from './anim.js';
import { solveIk } from './ik.js';

export class Emote {
  /** fx: 메시 없이 이펙트만 든 Model | null · props: [{model, clip, begin, end, abegin}] · ik: 손 IK (ik.js) */
  constructor(rig, fx, props, ik = []) {
    this.rig = rig;
    this.fx = fx;
    this.props = props;
    this.ik = ik;
  }

  /** 타임라인 name 을 불러온다 — urlOf(모델 id) → 주소. 소품 뼈·소켓(folder: 체형 폴더 것)은 rig 에 붙인다.
   *  그릴 것이 없으면 null. 소품 하나를 못 불러오면 그것만 빼고 (덤이다), 타임라인 자체를 못 읽으면 예외. */
  static async load(name, urlOf, rig, folder = '') {
    const id = 'tl:' + name;
    const url = await urlOf(id);
    const meta = await (await fetch(url)).json();
    rig.add(((meta && meta.sockets) || {})[folder] || []);
    let fx = null;
    if (meta && meta.fx) {
      const group = new THREE.Group();
      group.name = id;
      fx = new Model(id, meta, group, [], []);
      fx.fx = new FxPlayer(meta.fx, fx, fxTexture(fx, url));
    }
    const props = (await Promise.all(((meta && meta.props) || []).map(async (p) => {
      let model = null;
      try {
        model = await loadModel(p.model, await urlOf(p.model), rig);
        model.setShown(false);
        const node = model.meta.attach && model.meta.attach[0] && model.meta.attach[0].node;
        const clip = p.clip && node ? (await loadClip(await urlOf(p.clip))).rebase(node) : null;
        return { model, clip, begin: p.begin, end: p.end, abegin: p.abegin || 0 };
      } catch (e) {
        if (model) model.dispose();
        console.warn('감정 표현 소품을 불러오지 못했습니다', p.model, e);
        return null;
      }
    }))).filter(Boolean);
    const ik = (meta && meta.ik) || [];
    if (!fx && !props.length && !ik.length) return null;
    return new Emote(rig, fx, props, ik);
  }

  /** 장면에 넣을 모델들. */
  models() {
    return [this.fx, ...this.props.map((p) => p.model)].filter(Boolean);
  }

  /** 소품 자세·보이기 — rig.rest 와 몸 동작 뒤에. t: 이 단계 시간(초), null 이면 이 단계가 아니다 (숨긴다). */
  pose(rig, t) {
    const mine = rig === this.rig;
    for (const p of this.props) {
      const on = mine && t !== null && t >= p.begin && t < p.end;
      if (p.model.shown !== on) p.model.setShown(on);
      if (on && p.clip) p.clip.apply(rig, t - p.abegin, false);
    }
  }

  /** 손 IK — 몸 조절까지 다 얹은 뒤 (t: pose 와 같다). */
  reach(rig, t) {
    if (this.ik.length && rig === this.rig && t !== null) solveIk(rig, this.ik, t);
  }

  /** 이펙트 한 걸음 (fx.js FxPlayer.update — t 가 null 이면 멈춘다). */
  effects(dt, rig, camera, t) {
    if (this.fx && this.fx.fx) this.fx.fx.update(dt, rig, camera, rig === this.rig ? t : null);
  }

  dispose() {
    for (const m of this.models()) m.dispose();
  }
}
