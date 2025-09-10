#!/bin/bash

set -e

echo "Ingesting DIST-ALERTS"
uv run python stac/datasets/dist_alerts.py
echo "Ingesting GLOBAL LAND COVER"
uv run python stac/datasets/global_land_cover.py
echo "Ingesting GRASSLANDS"
uv run python stac/datasets/grasslands.py
echo "Ingesting NATURAL LANDS"
uv run python stac/datasets/natural_lands.py
echo "Ingesting TREE COVER LOSS"
uv run python stac/datasets/tree_cover_loss.py
echo "Done!"
