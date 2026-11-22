"""기능 코드가 Bot·GameSession 메서드를 받는 인자로만 부르나 — bot.X(...)·session.X(...) 호출을 그 메서드 모양에 대 본다.

시험의 가짜 봇은 GameSession 메서드를 바로 빌려 쓰기도 해서, Bot 래퍼가 새 인자를 안 받는 것을 못 잡는다
(2026-11-22 v3.30.9: Bot.in_combat 이 cli_first 를 받지 않아 보스 기술이 켜진 판마다 TypeError 로 뻗음).
코드를 돌리지 않고 글(AST)만 읽어 위치 인자 수·이름 인자를 맞춰 본다."""
import ast
import inspect
import unittest
from pathlib import Path

from mabi.bot import Bot
from mabi.session import GameSession

ROOT = Path(__file__).resolve().parent.parent
OWNERS = {"bot": Bot, "session": GameSession}   # 이 이름(변수·속성)으로 부르는 것을 그 클래스로 본다


def calls():
    for path in sorted([*ROOT.joinpath("mabi").rglob("*.py"), *ROOT.joinpath("gui_app").rglob("*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            owner = node.func.value
            name = owner.id if isinstance(owner, ast.Name) else owner.attr if isinstance(owner, ast.Attribute) else ""
            if name in OWNERS:
                yield path.relative_to(ROOT), OWNERS[name], node


def signature(cls, name: str):
    """(서명, 앞에 채울 자리) — 보통 메서드면 self 자리 하나. 속성·인스턴스 값이면 None."""
    raw = inspect.getattr_static(cls, name, None)
    if isinstance(raw, (staticmethod, classmethod)):
        return inspect.signature(getattr(cls, name)), ()
    if inspect.isfunction(raw):
        return inspect.signature(raw), (None,)
    return None


class BotCallTest(unittest.TestCase):
    def test_calls_fit(self):
        bad, seen = [], {Bot: 0, GameSession: 0}
        for path, cls, node in calls():
            sig = signature(cls, node.func.attr)
            if sig is None:
                continue
            if any(isinstance(a, ast.Starred) for a in node.args) or any(k.arg is None for k in node.keywords):
                continue   # *args·**kw 로 넘기는 것은 글만으로 못 맞춘다
            seen[cls] += 1
            try:
                sig[0].bind(*sig[1], *node.args, **{k.arg: None for k in node.keywords})
            except TypeError as e:
                bad.append(f"{path}:{node.lineno} {cls.__name__}.{node.func.attr}: {e}")
        self.assertGreater(seen[Bot], 200, "bot.X(...) 호출을 거의 못 찾음 — 찾는 법이 깨졌나")
        self.assertGreater(seen[GameSession], 20)
        self.assertEqual(bad, [])

    def test_catches_wrapper_drift(self):
        # 이번 사고 모양: 래퍼가 받지 않는 이름 인자
        node = ast.parse("bot.in_combat(act, cli_first=True, nope=1)").body[0].value
        sig = signature(Bot, "in_combat")
        with self.assertRaises(TypeError):
            sig[0].bind(*sig[1], *node.args, **{k.arg: None for k in node.keywords})


if __name__ == "__main__":
    unittest.main()
