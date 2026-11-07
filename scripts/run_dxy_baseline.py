"""Run the repository's DXY Diaformer baseline adapter."""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.knowledge.diaformer_baseline import main


if __name__ == "__main__":
    main()
