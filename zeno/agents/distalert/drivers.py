import ee

# Example from https://code.earthengine.google.com/06f83955d12f278414f8c53655abdd6d

DRIVER_VALUEMAP = {
    "wildfire": 1,
    "crop_cycle": 2,
    "flooding": 3,
    "conversion": 4,
    "other_conversion": 5,
}
GEE_FOLDER = "pojects/glad/HLSDIST/current/"

def get_drivers():
    natural_lands = ee.Image("WRI/SBTN/naturalLands/v1/2020").select("natural")
    vegdistcount = ee.ImageCollection(GEE_FOLDER + "VEG-DIST-COUNT").mosaic()
    veganommax = ee.ImageCollection(GEE_FOLDER + "VEG-ANOM-MAX").mosaic()
    confmask = vegdistcount.gte(2).And(veganommax.gt(50))

    wf_collection = ee.ImageCollection.fromImages(
        [
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-africa-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-europe-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-latam-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-ne-asia-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-north-am-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/wildfire/dist-alert-wildfire-se-asia-oceania-nov2023-oct2024_v01"
            ),
        ]
    )

    wildfire = (
        wf_collection.mosaic()
        .neq(0)
        .updateMask(confmask)
        .updateMask(natural_lands)
    )

    cc_collection = ee.ImageCollection.fromImages(
        [
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-africa-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-europe-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-latam-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-northam-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-seasia_oceania-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-crop-cycle-neasia-nov2023-oct2024-tiles-all"
            ),
        ]
    )

    crop_cycle = cc_collection.mosaic().updateMask(confmask)

    fl_collection = ee.ImageCollection.fromImages(
        [
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-africa-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-europe-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-latam-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-northam-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-seasia-oceania-nov2023-oct2024-tiles-all"
            ),
            ee.Image(
                "projects/ee-jamesmaccarthy-wri/assets/dist-alert-flooding-neasia-nov2023-oct2024-tiles-all"
            ),
        ]
    )

    flooding = (
        fl_collection.mosaic()
        .updateMask(confmask)
        .updateMask(crop_cycle.unmask(2).neq(1))
        .updateMask(wildfire.eq(0).unmask(1))
    )

    cv_collection = ee.ImageCollection.fromImages(
        [
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-africa-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-europe-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-latam-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-ne-asia-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-north-am-nov2023-oct2024_v01"
            ),
            ee.Image(
                "projects/wri-dist-alert-drivers/assets/conversion/dist-alert-conversion-se-asia-oceania-nov2023-oct2024_v01"
            ),
        ]
    )

    conversion = (
        cv_collection.mosaic()
        .updateMask(confmask)
        .updateMask(natural_lands)
        .updateMask(crop_cycle.unmask(2).neq(1))
        .updateMask(wildfire.unmask(2).neq(1))
    )

    other_conversion = (
        cv_collection.mosaic()
        .updateMask(confmask)
        .updateMask(natural_lands.eq(0))
        .updateMask(crop_cycle.unmask(2).neq(1))
        .updateMask(wildfire.unmask(2).neq(1))
    )

    combo = (
        wildfire.multiply(DRIVER_VALUEMAP["wildfire"])
        .unmask()
        .add(crop_cycle.multiply(DRIVER_VALUEMAP["crop_cycle"]).unmask())
        .add(flooding.multiply(DRIVER_VALUEMAP["flooding"]).unmask())
        .add(conversion.multiply(DRIVER_VALUEMAP["conversion"]).unmask())
        .add(
            other_conversion.multiply(
                DRIVER_VALUEMAP["other_conversion"]
            ).unmask()
        )
    )
    combo_mask = (
        wildfire.mask()
        .Or(crop_cycle.mask())
        .Or(flooding.mask())
        .Or(conversion.mask())
        .Or(other_conversion.mask())
    )
    combo = combo.updateMask(combo_mask)

    return combo
