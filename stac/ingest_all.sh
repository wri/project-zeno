#!/bin/bash

set -e

echo "Ingesting DIST-ALERTS"
python stac/datasets/dist_alerts.py
echo "Ingesting GLOBAL LAND COVER"
python stac/datasets/global_land_cover.py
echo "Ingesting GRASSLANDS"
python stac/datasets/grasslands.py
echo "Ingesting NATURAL LANDS"
python stac/datasets/natural_lands.py
echo "Ingesting TREE COVER LOSS"
python stac/datasets/tree_cover_loss.py
echo "Done!"
