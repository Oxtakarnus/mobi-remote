"""드레스룸 표정 키 (mabi.dress.xaf) — 게임 파일 없이 만든 XAF 내용으로."""
import unittest

from mabi.dress import xaf as X


def key(t, v, tin="Flat", tout=None):
    return {"Time": t, "Value": v, "InTangentType": tin, "OutTangentType": tout or tin}


class XafTest(unittest.TestCase):
    def test_path_for(self):
        self.assertEqual(
            X.path_for("Assets/PatchableAssets/Animation/Player/Human/Female/PlayerCommon/_FaceOnly/HF@A_Facial.fbx"),
            "Animation/XafAnimation/Animation/Player/Human/Female/PlayerCommon/_FaceOnly/HF@A_Facial.xaf.sjon.bin")

    def test_sample_hold_and_range(self):
        keys = [key(0, 1, "Constant"), key(6, 25, "Constant")]
        self.assertEqual(X.sample(keys, -3), 1)
        self.assertEqual(X.sample(keys, 5.9), 1)      # 앞 키 값 그대로
        self.assertEqual(X.sample(keys, 6), 25)
        self.assertEqual(X.sample(keys, 99), 25)      # 범위 밖은 끝 키
        step = [key(0, 1, "Step"), key(4, 3, "Linear")]
        self.assertEqual(X.sample(step, 2), 1)        # 앞 키 Out 이 Step 이면 그대로

    def test_sample_curves(self):
        lin = [key(0, 0, "Linear"), key(10, 100, "Linear")]
        self.assertAlmostEqual(X.sample(lin, 2.5), 25)
        flat = [key(0, 0), key(10, 100)]
        self.assertAlmostEqual(X.sample(flat, 5), 50)
        self.assertLess(X.sample(flat, 1), 10)       # 기울기 0 으로 천천히 떠난다
        auto = [key(0, 0, "Auto"), key(5, 100, "Auto"), key(10, 0, "Auto")]
        self.assertAlmostEqual(X.sample(auto, 5), 100)
        self.assertLessEqual(max(X.sample(auto, f / 4) for f in range(41)), 100)   # 꼭짓점에서 넘치지 않는다

    def test_convert(self):
        d = {"StartFrame": 0, "EndFrame": 4, "FrameRate": 30, "AnimationDatas": [
            {"AnimationObjectName": "Mesh_Skin_Head", "KeyframeTracks": [
                {"AnimationType": "Shader", "AnimationPropertyName": "_MouthShowType", "Keyframes": [key(0, 1, "Constant"), key(4, 1, "Constant")]},
                {"AnimationType": "Shader", "AnimationPropertyName": "_EmotionMouthMapAtlasSize.z", "Keyframes": [key(0, 1, "Constant"), key(2, 25, "Constant")]}]},
            {"AnimationObjectName": "Mesh_EyeBase_L", "KeyframeTracks": [
                {"AnimationType": "Morpher", "AnimationPropertyName": "MT_BlinkDown_L", "Keyframes": [key(0, 0, "Linear"), key(4, 100, "Linear")]},
                {"AnimationType": "Visibility", "AnimationPropertyName": "visibility", "Keyframes": [key(0, 0, "Constant")]},
                {"AnimationType": "Position", "AnimationPropertyName": "x", "Keyframes": [key(0, 0)]}]}]}
        out = X.convert(d)
        self.assertEqual((out["fps"], out["frames"]), (30.0, 5))
        tr = {(t["o"], t["p"]): t for t in out["tracks"]}
        self.assertEqual(len(tr), 4)                                        # 모르는 종류는 뺀다
        self.assertEqual(tr["Mesh_Skin_Head", "_MouthShowType"]["v"], [1])   # 내내 같으면 하나
        self.assertEqual(tr["Mesh_Skin_Head", "_EmotionMouthMapAtlasSize.z"]["v"], [1, 1, 25, 25, 25])
        self.assertEqual(tr["Mesh_EyeBase_L", "MT_BlinkDown_L"]["v"], [0, 0.25, 0.5, 0.75, 1])   # % → 0~1
        self.assertEqual(tr["Mesh_EyeBase_L", "Visibility"]["t"], "vis")    # 소문자로 적힌 것도
        self.assertIsNone(X.convert({"AnimationDatas": []}))


if __name__ == "__main__":
    unittest.main()
