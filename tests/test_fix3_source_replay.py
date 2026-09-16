from pathlib import Path

import pytest

from tools.fix3.replay_source_operator import native_source


def test_native_replay_refuses_missing_source_anchors(tmp_path: Path):
    source = tmp_path / "dfs.F90"
    source.write_text("! Different lineage; do not silently use Chamoli expressions\n")
    with pytest.raises(ValueError, match="ambiguous source anchor"):
        native_source(source)
