"""드레스룸 전체 의상 점검 (콘솔). 사용법은 mabi/dress/audit.py 맨 위 설명."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mabi.dress.audit import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
