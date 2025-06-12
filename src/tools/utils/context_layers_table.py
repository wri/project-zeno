from pathlib import Path
import lancedb

data_dir = Path("data")

table = lancedb.connect(data_dir / "layers-context").open_table(
    "zeno-layers-context-latest"
)
