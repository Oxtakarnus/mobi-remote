"""드레스룸 동작 목록 (mabi.dress.motions) — 시트 대신 만든 행·경로로."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mabi.dress import anim as N
from mabi.dress import catalog as C
from mabi.dress import motions as M
from mabi.dress import service as S

F = C.ANIM + "Female/"


def paths(*names):
    """'Customize/HF@…' 꼴 → 자산 경로 (.fbx)."""
    return [F + n + ".fbx" for n in names]


PATHS = paths(
    "Stand/Default/HF@Stand_Default_01", "Stand/Thin/HF@Stand_Thin_01",
    "PlayerCommon/HF@PlayerCommon_Walk", "PlayerCommon/HF@PlayerCommon_Walk_Facial",
    "PlayerCommon/HF@PlayerCommon_Run", "PlayerCommon/HF@PlayerCommon_Run_Fat_Fixed",
    "PlayerCommon/HF@PlayerCommon_Stand", "PlayerCommon/HF@PlayerCommon_Stand_Fat", "PlayerCommon/HF@PlayerCommon_Stand_Offensive",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Bye_01", "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Bye_01_Facial",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_90bow",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_MagicHat_Start",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_MagicHat_Loop",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_MagicHat_End",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Balloon_Start_01",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Balloon_Loop_01",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Balloon_Loop_02",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Carry_Host_Loop",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Carry_Guest_Loop",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Hug_Fail",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_Hug_Loop",
    "PlayerCommon/_Sit/HF@PlayerCommon_Sit_Pool_Rest_Loop",
    "PlayerCommon/_Emotion/HF@PlayerCommon_Emotion_LectureStand",
    "Customize/HF@Customize_Stand_Default", "Customize/HF@Customize_Stand_Fat",
    "Customize/HF@Customize_Pose_01_Default", "Customize/HF@Customize_Pose_01_Default_Facial",
    "Customize/HF@Customize_Costume_02_Default_Start", "Customize/HF@Customize_Costume_02_Default_Loop",
    "Customize/HF@Customize_Stand_Start_01_Default",
    "PlayerCommon/_FaceOnly/HF@PlayerCommon_FaceOnly_Grin_Facial",
) + [C.ANIM + "Female/Battle/HF@Attack.fbx", C.ANIM + "Male/Customize/HM@Customize_Stand_Default.fbx",
      F + "NoviceWarrior/HF@NoviceWarrior_Alert_Stand.fbx", F + "NoviceArcher/HF@NoviceArcher_Alert_Stand.fbx",
      F + "NoviceArcher/HF@NoviceArcher_Alert_Stand_Fat.fbx", F + "NoviceWarrior/HF@NoviceWarrior_Combat_Stand.fbx",
      C.ANIM + "Male/GreatSword/HM@GreatSword_Groggy_Start.fbx"]

ROWS = [
    ("PlayerFemale", "Any", "PeaceStand", F + "Stand/Default/HF@Stand_Default_01.fbx"),
    ("PlayerFemale", "Any", "PeaceWalk", F + "PlayerCommon/HF@PlayerCommon_Walk.fbx"),
    ("PlayerFemale", "Any", "AlertWalk", F + "PlayerCommon/HF@PlayerCommon_Walk.fbx"),
    ("PlayerFemale", "Any", "PeaceRun", F + "PlayerCommon/HF@PlayerCommon_Run.fbx"),
    ("PlayerFemale", "Any", "BodyDiversityCommonStand", F + "PlayerCommon/HF@PlayerCommon_Stand.fbx"),
    ("PlayerFemale", "Any", "ChairSit", F + "PlayerCommon/_Sit/HF@PlayerCommon_ChairSitting02_Loop.fbx"),
    ("PlayerFemale", "Any", "AlertStand", F + "PlayerCommon/HF@PlayerCommon_Stand_Offensive.fbx"),
    ("PlayerFemale", "CombatJob:Warrior", "AlertStand", F + "NoviceWarrior/HF@NoviceWarrior_Alert_Stand.fbx"),
    ("PlayerFemale", "CombatJob:HighWarrior", "AlertStand", F + "NoviceWarrior/HF@NoviceWarrior_Alert_Stand.fbx"),
    ("PlayerFemale", "CombatJob:Archer", "AlertStand", F + "NoviceArcher/HF@NoviceArcher_Alert_Stand.fbx"),
    ("PlayerFemale", "CombatJob:Archer, BodyType:Fat", "AlertStand", F + "NoviceArcher/HF@NoviceArcher_Alert_Stand_Fat.fbx"),
    ("PlayerFemale", "CombatJob:Mage", "AlertStand", F + "NoviceMage/HF@NoviceMage_Alert_Stand.fbx"),   # 파일 없음
    ("PlayerFemale", "Additional:SwordMaster_SwiftPosture, CombatJob:SwordMaster", "AlertStand",
     F + "NoviceWarrior/HF@NoviceWarrior_Combat_Stand.fbx"),                                            # 덧붙은 갈래는 뺀다
    ("PlayerFemale", "Any", "CombatStand", F + "PlayerCommon/HF@PlayerCommon_Stand_Offensive.fbx"),
    ("PlayerFemale", "CombatJob:Warrior", "CombatStand", F + "NoviceWarrior/HF@NoviceWarrior_Combat_Stand.fbx"),
    ("PlayerFemale", "Any", "InventoryPose", F + "PlayerCommon/HF@PlayerCommon_Stand_Offensive.fbx"),
    ("PlayerFemale", "CombatJob:Warrior", "InventoryPose", F + "NoviceWarrior/HF@NoviceWarrior_Alert_Stand.fbx"),
    ("PlayerFemale", "Any", "GroggyHit", F + "PlayerCommon/HF@PlayerCommon_Run.fbx"),
    ("PlayerFemale", "CombatJob:GreatSwordWarrior", "GroggyHit", C.ANIM + "Male/GreatSword/HM@GreatSword_Groggy_Start.fbx"),
    ("PlayerFemale", "Gender:Female, BodyType:Thin", "PeaceStand", F + "Stand/Thin/HF@Stand_Thin_01.fbx"),
    ("PlayerFemale", "Gender:Female, BodyType:Fat", "PeaceRun", F + "PlayerCommon/HF@PlayerCommon_Run_Fat_Fixed.fbx"),
    ("PlayerMale", "Any", "PeaceWalk", C.ANIM + "Male/PlayerCommon/HM@PlayerCommon_Walk.fbx"),
]
SOCIAL = [("손인사1", "Bye_01"), ("격식인사", "Bow90"), ("모자마술", "MagicHat_00"), ("풍선", "Balloon_01"),
          ("안기", "Carry"), ("포옹", "Hug"), ("앉기", "Rest"), ("없는 것", "Nothing")]


class NameTest(unittest.TestCase):
    def test_norm_of(self):
        self.assertEqual(M.norm_of("HF@PlayerCommon_Run_Fat_Fixed"), ("hf@playercommon_run_fixed", "Fat"))
        self.assertEqual(M.norm_of("HF@Customize_Stand_Muscle"), ("hf@customize_stand", "Muscular"))
        self.assertEqual(M.norm_of("HF@PlayerCommon_Walk"), ("hf@playercommon_walk", ""))

    def test_tokens(self):
        self.assertEqual(M.tokens("Bow90"), {"bow", "90"})
        self.assertEqual(M.tokens("HF@PlayerCommon_Emotion_90bow"), {"hf", "player", "common", "emotion", "90", "bow"})

    def test_index(self):
        idx = M.index(PATHS)
        self.assertIn("HF@PlayerCommon_Walk", idx["Female"])
        self.assertNotIn("HF@Attack", idx["Female"])          # 동작 폴더 밖
        self.assertIn("HF@Attack", M.index(PATHS, every=True)["Female"])   # 직업 갈래용 — 사람 동작 전부
        self.assertIn("HM@Customize_Stand_Default", idx["Male"])
        self.assertEqual(idx["Infant"], {})

    def test_shaped(self):
        clips = M.Clips(M.index(PATHS)["Female"])
        self.assertEqual(clips.shaped("HF@PlayerCommon_Stand"),
                         {"": "HF@PlayerCommon_Stand", "Thin": "HF@PlayerCommon_Stand",
                          "Fat": "HF@PlayerCommon_Stand_Fat", "Muscular": "HF@PlayerCommon_Stand"})


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.clips = M.Clips(M.index(PATHS)["Female"])

    def test_common(self):
        out = M.common(ROWS, "Female", self.clips, M.index(PATHS, every=True)["Female"])
        by = {e["id"]: e for e in out}
        # STATES 순서, 의자 없음. 경계 걷기는 걷기와 같은 파일에 직업 갈래도 없어 뺀다. 가방 자세는 기본 파일이
        # 경계 자세와 같아도 직업 갈래가 달라 따로. 비틀거리기는 직업 파일이 다른 체형 폴더에 있어 이 폴더 것만으론 달리기와 같다
        self.assertEqual([e["name"] for e in out], ["서 있기", "기본 자세", "경계 자세", "전투 자세", "가방 자세", "걷기", "달리기"])
        # 직업별 갈래가 있는 상태만 무기를 꺼내 든다
        self.assertEqual([e["id"] for e in out if e.get("drawn")], ["s:AlertStand", "s:CombatStand", "s:InventoryPose"])
        self.assertEqual(by["s:AlertStand"]["steps"], {"": ["HF@PlayerCommon_Stand_Offensive"]})
        # 직업별 동작 — 셰이프 갈래, 파일 없는 직업·덧붙은 갈래는 뺀다
        self.assertEqual(by["s:AlertStand"]["jobs"], {
            "Archer": {"": ["HF@NoviceArcher_Alert_Stand"], "Fat": ["HF@NoviceArcher_Alert_Stand_Fat"]},
            "HighWarrior": {"": ["HF@NoviceWarrior_Alert_Stand"]}, "Warrior": {"": ["HF@NoviceWarrior_Alert_Stand"]}})
        self.assertEqual(by["s:CombatStand"]["jobs"], {"Warrior": {"": ["HF@NoviceWarrior_Combat_Stand"]}})
        self.assertEqual(by["s:PeaceStand"]["steps"], {"": ["HF@Stand_Default_01"], "Thin": ["HF@Stand_Thin_01"]})
        self.assertEqual(by["s:PeaceRun"]["steps"], {"": ["HF@PlayerCommon_Run"], "Fat": ["HF@PlayerCommon_Run_Fat_Fixed"]})
        self.assertEqual(by["s:BodyDiversityCommonStand"]["steps"]["Fat"], ["HF@PlayerCommon_Stand_Fat"])
        self.assertNotIn("s:AlertWalk", by)   # STATES 에 없는 상태

    def test_customize(self):
        out = M.customize(self.clips)
        self.assertEqual([e["name"] for e in out], ["대기 시작 1", "대기", "포즈 1", "의상 포즈 2"])
        by = {e["id"]: e for e in out}
        self.assertEqual(by["c:Stand"]["steps"], {"": ["HF@Customize_Stand_Default"], "Fat": ["HF@Customize_Stand_Fat"]})
        self.assertEqual(by["c:Costume_02"]["steps"],
                         {"": ["HF@Customize_Costume_02_Default_Start", "HF@Customize_Costume_02_Default_Loop"]})

    def test_social(self):
        m = lambda k: M.match_social(k, self.clips)
        self.assertEqual(m("Bye_01"), ["HF@PlayerCommon_Emotion_Bye_01"])
        self.assertEqual(m("Bow90"), ["HF@PlayerCommon_Emotion_90bow"])          # 낱말 순서가 다른 것
        self.assertEqual(m("MagicHat_00"), ["HF@PlayerCommon_Emotion_MagicHat_Start",   # 붙은 번호 없이, 끝내기는 뺀다
                                            "HF@PlayerCommon_Emotion_MagicHat_Loop"])
        self.assertEqual(m("Balloon_01"), ["HF@PlayerCommon_Emotion_Balloon_Start_01",   # 단계 뒤 번호
                                           "HF@PlayerCommon_Emotion_Balloon_Loop_01"])
        self.assertEqual(m("Carry"), ["HF@PlayerCommon_Emotion_Carry_Host_Loop"])   # 두 사람 동작은 한 사람 몫
        self.assertEqual(m("Hug"), ["HF@PlayerCommon_Emotion_Hug_Loop"])            # 실패 동작은 빼고
        self.assertIsNone(m("Rest"))       # 글자만 겹치는 것(LectureStand)·소품 동작(Sit_Pool_Rest)은 아니다
        self.assertIsNone(m("Nothing"))


FACE = [("미소", "😁", ["HM@PlayerCommon_FaceOnly_Grin_Facial.fbx", "HF@PlayerCommon_FaceOnly_Grin_Facial.fbx",
                        "HC@PlayerCommon_FaceOnly_Grin_Facial.fbx"]),
        ("윙크", "😉", ["HM@PlayerCommon_FaceOnly_Wink_Facial.fbx", "HF@PlayerCommon_FaceOnly_Wink_Facial.fbx",
                        "HC@PlayerCommon_FaceOnly_Wink_Facial.fbx"])]   # 윙크는 파일이 없다


class BuildTest(unittest.TestCase):
    def test_build(self):
        with (mock.patch.object(M, "state_rows", return_value=ROWS), mock.patch.object(M, "social_rows", return_value=SOCIAL),
              mock.patch.object(M, "face_rows", return_value=FACE)):
            t = M.build(object(), PATHS)
        ids = [e["id"] for e in t["list"]]
        self.assertEqual([e["cat"] for e in t["list"]][:1], ["common"])
        self.assertLess(ids.index("c:Stand"), ids.index("e:Bye_01"))   # 공통 → 꾸미기 → 감정 표현
        self.assertNotIn("e:Rest", ids)
        stand = next(e for e in t["list"] if e["id"] == "c:Stand")
        self.assertEqual(set(stand["steps"]), {"Female", "Male"})
        self.assertEqual([e["id"] for e in t["list"] if e.get("drawn")],
                         ["s:AlertStand", "s:CombatStand", "s:InventoryPose", "s:GroggyHit"])   # 체형 폴더를 합쳐도 남는다
        alert = next(e for e in t["list"] if e["id"] == "s:AlertStand")
        self.assertEqual(alert["jobs"]["Warrior"], {"Female": {"": ["HF@NoviceWarrior_Alert_Stand"]}})
        # 직업 갈래가 다른 체형 폴더 파일을 써도 (대검전사 비틀거리기 — 여성이 남성 클립) 클립 목록에 든다
        groggy = next(e for e in t["list"] if e["id"] == "s:GroggyHit")
        self.assertEqual(groggy["jobs"]["GreatSwordWarrior"]["Female"], {"": ["HM@GreatSword_Groggy_Start"]})
        self.assertIn("HM@GreatSword_Groggy_Start", t["clips"])
        self.assertIn("HF@NoviceArcher_Alert_Stand_Fat", t["clips"])
        self.assertEqual(t["facial"], {"HF@PlayerCommon_Walk": "HF@PlayerCommon_Walk_Facial",
                                       "HF@PlayerCommon_Emotion_Bye_01": "HF@PlayerCommon_Emotion_Bye_01_Facial",
                                       "HF@Customize_Pose_01_Default": "HF@Customize_Pose_01_Default_Facial"})
        self.assertEqual(t["clips"]["HF@PlayerCommon_Walk_Facial"], F + "PlayerCommon/HF@PlayerCommon_Walk_Facial.fbx")
        self.assertNotIn("HF@Attack", t["clips"])
        pub = M.public(t)
        self.assertNotIn("clips", pub)
        self.assertEqual([c["id"] for c in pub["cats"]], ["common", "customize", "emotion", "face"])
        face = [e for e in t["list"] if e["cat"] == "face"]   # 표정 — 그 체형 파일이 있는 것만, 단계는 표정 줄기 하나
        self.assertEqual(face, [{"id": "f:Grin", "cat": "face", "name": "😁 미소",
                                 "steps": {"Female": {"": ["HF@PlayerCommon_FaceOnly_Grin_Facial"]}}}])
        self.assertIn("HF@PlayerCommon_FaceOnly_Grin_Facial", t["clips"])
        self.assertNotIn("HF@PlayerCommon_FaceOnly_Grin_Facial", t["facial"])

    def test_without_sheets(self):
        t = M.build(None, PATHS)   # 시트를 못 읽으면 꾸미기만
        self.assertEqual({e["cat"] for e in t["list"]}, {"customize"})


class ServiceClipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.room = S.DressRoom(Path(self.tmp.name), game_dir=lambda: None)
        self.room._motions = M.build(None, PATHS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fbx(self):
        self.assertEqual(self.room._fbx("clip:HF@Customize_Stand_Fat"), ("anim", F + "Customize/HF@Customize_Stand_Fat.fbx"))
        self.assertEqual(self.room._fbx("clip:HF@Customize_Pose_01_Default_Facial"),
                         ("facial", F + "Customize/HF@Customize_Pose_01_Default_Facial.fbx"))
        for bad in ("clip:HF@Attack", "clip:"):
            with self.assertRaises(S.DressError, msg=bad):
                self.room._fbx(bad)

    def test_pick_clip(self):
        c = lambda n: mock.Mock(m_Name=n)
        a, b = c("HF@Other"), c("HF@PlayerCommon_FaceOnly_Sob_Facial")
        self.assertIs(N.pick_clip([a, b], "HF@PlayerCommon_FaceOnly_Sob_Facial"), b)   # 묶음 첫 클립이 아니라 그 파일 것
        f = c("HF@PlayerCommon_Emotion_FollowMe")
        self.assertIs(N.pick_clip([a, f], "HF@PlayerCommon_Emotion_Followme"), f)      # 대소문자만 다른 것
        one = c("HF@PlayerCommon_Emotion_SnowSpray_Loop")
        self.assertIs(N.pick_clip([one], "HF@PlayerCommon_Emotion_SnowSpray"), one)    # 하나뿐이면 그것
        st, lp = c("HF@PlayerCommon_Emotion_Yoga_Start_Facial"), c("HF@PlayerCommon_Emotion_Yoga_Loop_Facial")
        self.assertIs(N.pick_clip([st, lp], "HF@PlayerCommon_Emotion_Yoga_Facial"), lp)   # 시작·반복이 함께 든 파일 → 반복
        self.assertIsNone(N.pick_clip([a, st], "HF@Nothing"))

    def test_face_only(self):
        self.assertTrue(N.face_only("Bip/_COM/_Pelvis/_Spine/_Neck/_Head/_Jaw"))
        self.assertFalse(N.face_only("Bip/_COM/_Pelvis/_Spine/_Neck/_Head"))


if __name__ == "__main__":
    unittest.main()
