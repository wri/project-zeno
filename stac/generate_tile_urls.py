import json
import urllib.parse


def generate_colormap(land_cover_classes, enabled_classes):
    """
    Generate colormap for enabled classes.

    Args:
        land_cover_classes (dict): Dictionary of land cover classes with colors
        enabled_classes (set): Set of enabled class IDs as strings

    Returns:
        dict: Colormap with only enabled classes
    """
    colormap = {}

    for class_id, class_info in land_cover_classes.items():
        if class_id in enabled_classes:
            colormap[class_id] = class_info["color"]
        else:
            colormap[class_id] = [
                0,
                0,
                0,
                0,
            ]  # Transparent for disabled classes

    return colormap


global_land_cover_classes = {
    "1": {
        "name": "Bare ground & sparse vegetation",
        "color": [139, 69, 19, 255],
    },
    "2": {"name": "Short vegetation", "color": [255, 255, 0, 255]},
    "3": {"name": "Tree cover", "color": [0, 128, 0, 255]},
    "4": {"name": "Wetland - short vegetation", "color": [0, 255, 255, 255]},
    "5": {"name": "Water", "color": [0, 0, 255, 255]},
    "6": {"name": "Snow/ice", "color": [255, 255, 255, 255]},
    "7": {"name": "Cropland", "color": [255, 0, 0, 255]},
    "8": {"name": "Built-up", "color": [128, 128, 128, 255]},
    "9": {"name": "Cultivated grasslands", "color": [255, 165, 0, 255]},
}

natural_lands_classes = {
    "2": {
        "name": "Natural forests",
        "color": [36, 110, 36, 255],
        "natural": True,
    },
    "3": {
        "name": "Natural short vegetation",
        "color": [185, 185, 30, 255],
        "natural": True,
    },
    "4": {
        "name": "Natural water",
        "color": [107, 174, 214, 255],
        "natural": True,
    },
    "5": {"name": "Mangroves", "color": [6, 162, 133, 255], "natural": True},
    "6": {"name": "Bare", "color": [254, 254, 204, 255], "natural": True},
    "7": {"name": "Snow", "color": [172, 209, 232, 255], "natural": True},
    "8": {
        "name": "Wet natural forests",
        "color": [88, 149, 88, 255],
        "natural": True,
    },
    "9": {
        "name": "Natural peat forests",
        "color": [9, 61, 9, 255],
        "natural": True,
    },
    "10": {
        "name": "Wet natural short vegetation",
        "color": [219, 219, 123, 255],
        "natural": True,
    },
    "11": {
        "name": "Natural peat short vegetation",
        "color": [153, 153, 26, 255],
        "natural": True,
    },
    "12": {"name": "Crop", "color": [211, 211, 211, 255], "natural": False},
    "13": {"name": "Built", "color": [211, 211, 211, 255], "natural": False},
    "14": {
        "name": "Non-natural tree cover",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "15": {
        "name": "Non-natural short vegetation",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "16": {
        "name": "Non-natural water",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "17": {
        "name": "Wet non-natural tree cover",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "18": {
        "name": "Non-natural peat tree cover",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "19": {
        "name": "Wet non-natural short vegetation",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "20": {
        "name": "Non-natural peat short vegetation",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
    "21": {
        "name": "Non-natural bare",
        "color": [211, 211, 211, 255],
        "natural": False,
    },
}


grasslands_classes = {
    "0": {"name": "Other", "color": [128, 128, 128, 255]},
    "1": {
        "name": "Cultivated grassland",
        "color": [255, 194, 102, 255],
    },
    "2": {
        "name": "Natural/semi-natural grassland",
        "color": [255, 153, 22, 255],
    },
    "3": {
        "name": "Open Shrubland",
        "color": [102, 179, 102, 255],
    },
}


def generate_tile_url_template(
    collection_name,
    colormap,
    expression=None,
    base_url="https://eoapi.zeno-staging.ds.io",
):
    """
    Generate tile URL templates for different raster collections.

    Args:
        collection_name (str): Name of the raster collection (e.g., 'global-land-cover-v-2', 'natural-lands-v-1-1')
        colormap (dict): Colormap dictionary mapping values to colors
        expression (str, optional): STAC expression for filtering data
        base_url (str): Base URL for the API

    Returns:
        str: Tile URL template with {z}/{x}/{y} placeholders
    """
    # Encode the colormap as JSON and then URL encode it
    colormap_encoded = urllib.parse.quote(json.dumps(colormap))

    # Build the base tile URL template
    tile_url_template = f"{base_url}/raster/collections/{collection_name}/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png"

    # Add query parameters
    params = []
    params.append(f"colormap={colormap_encoded}")
    params.append("assets=asset")

    if expression:
        expression_encoded = urllib.parse.quote(expression)
        params.append(f"expression={expression_encoded}")

    params.append("asset_as_band=True")

    # Combine URL template and parameters
    full_template = f"{tile_url_template}?{'&'.join(params)}"

    return full_template


def get_collection_colormap(collection_type):
    """
    Get the appropriate colormap for a collection type.

    Args:
        collection_type (str): Type of collection ('global_land_cover', 'natural_lands', 'grasslands')

    Returns:
        dict: Colormap dictionary
    """
    colormaps = {
        "global_land_cover": global_land_cover_classes,
        "natural_lands": natural_lands_classes,
        "grasslands": grasslands_classes,
    }

    return colormaps.get(collection_type, {})


def create_tile_url_template_for_collection(
    collection_type, collection_name, expression=None
):
    """
    Create tile URL templates for a specific collection type.

    Args:
        collection_type (str): Type of collection ('global_land_cover', 'natural_lands', 'grasslands')
        collection_name (str): STAC collection name
        expression (str, optional): STAC expression

    Returns:
        str: Tile URL template with {z}/{x}/{y} placeholders
    """
    colormap = get_collection_colormap(collection_type)
    if not colormap:
        raise ValueError(f"Unknown collection type: {collection_type}")

    return generate_tile_url_template(collection_name, colormap, expression)


# Template functions
def get_global_land_cover_template(enabled_classes=None):
    """Get tile URL template for global land cover collection."""
    if enabled_classes is None:
        enabled_classes = set(global_land_cover_classes.keys())

    dynamic_colormap = generate_colormap(
        global_land_cover_classes, enabled_classes
    )
    return generate_tile_url_template(
        "global-land-cover-v-2",
        dynamic_colormap,
        expression="asset*(asset<9)*(asset>=0)",
    )


def get_natural_lands_template(enabled_classes=None):
    """Get tile URL template for natural lands collection."""
    if enabled_classes is None:
        enabled_classes = set(natural_lands_classes.keys())

    dynamic_colormap = generate_colormap(
        natural_lands_classes, enabled_classes
    )
    return generate_tile_url_template(
        "natural-lands-v-1-1",
        dynamic_colormap,
        expression="asset*(asset<22)*(asset>1)",
    )


def get_grasslands_template(enabled_classes=None):
    """Get tile URL template for grasslands collection."""
    if enabled_classes is None:
        enabled_classes = set(grasslands_classes.keys())

    dynamic_colormap = generate_colormap(grasslands_classes, enabled_classes)
    return generate_tile_url_template(
        "grasslands-v-1-1",
        dynamic_colormap,
        expression="asset*(asset<4)*(asset>=0)",
    )


# Test with all classes enabled (default behavior)
print("=== All classes enabled ===")
print(get_global_land_cover_template())
print(get_natural_lands_template())
print(get_grasslands_template())

# Test with only specific classes enabled
print("\n=== Only natural forests and water enabled ===")
enabled_natural = {"2", "4"}  # Natural forests and natural water
print(get_natural_lands_template(enabled_natural))

print("\n=== Only grasslands enabled ===")
enabled_grasslands = {
    "2",
}  # Natural/semi-natural grassland and open shrubland
print(get_grasslands_template(enabled_grasslands))
