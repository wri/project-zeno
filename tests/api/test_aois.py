"""Tests for the unified AOI search endpoint (GET /api/aois).

Search reads the unified ``aois`` table, which is part of the ORM metadata, so
reference sources can be seeded directly here -- custom areas still arrive
through ``POST /api/custom_areas`` and its mirror, exercising the write path
that search depends on.
"""

import pytest
from sqlalchemy import text

from tests.conftest import async_session_maker, rebuild_search_tokens
from tests.conftest import seed_reference_aoi as _seed_reference_aoi

_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [29.2263174, -1.641965],
            [29.2263174, -1.665582],
            [29.2301511, -1.665582],
            [29.2301511, -1.641965],
            [29.2263174, -1.641965],
        ]
    ],
}

AUTH = {"Authorization": "Bearer abc123"}


async def _create_area(client, name):
    res = await client.post(
        "/api/custom_areas",
        json={"name": name, "geometries": [_POLYGON]},
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_search_by_name(auth_override, client):
    auth_override("test-user-wri")
    await _create_area(client, "Amazon")
    await _create_area(client, "Amazonia")
    await _create_area(client, "Sahara")

    res = await client.get("/api/aois?name=amazon", headers=AUTH)
    assert res.status_code == 200, res.text
    results = res.json()
    names = [r["name"] for r in results]
    assert "Amazon" in names
    assert "Amazonia" in names
    assert "Sahara" not in names
    # The exact-match custom area is returned with the expected shape.
    amazon = next(r for r in results if r["name"] == "Amazon")
    assert amazon["source"] == "custom"
    assert amazon["subtype"] == "custom-area"
    assert len(amazon["bbox"]) == 4


@pytest.mark.asyncio
async def test_browse_custom_without_name(auth_override, client):
    auth_override("test-user-wri")
    await _create_area(client, "Area B")
    await _create_area(client, "Area A")
    await _create_area(client, "Area C")

    res = await client.get("/api/aois?source=custom", headers=AUTH)
    assert res.status_code == 200, res.text
    names = [r["name"] for r in res.json()]
    # Browse mode is ordered alphabetically by name.
    assert names == ["Area A", "Area B", "Area C"]


@pytest.mark.asyncio
async def test_results_scoped_to_owner(auth_override, client, user_ds):
    auth_override("test-user-wri")
    await _create_area(client, "Owned Area")

    # A different user must not see another user's custom areas.
    # (user_ds is pre-created so auth resolves it by id without an email clash.)
    auth_override("test-user-ds")
    res = await client.get("/api/aois?source=custom", headers=AUTH)
    assert res.status_code == 200, res.text
    assert res.json() == []


@pytest.mark.asyncio
async def test_pagination(auth_override, client):
    auth_override("test-user-wri")
    for name in ["Area A", "Area B", "Area C"]:
        await _create_area(client, name)

    first = await client.get("/api/aois?source=custom&limit=2", headers=AUTH)
    assert first.status_code == 200, first.text
    assert [r["name"] for r in first.json()] == ["Area A", "Area B"]
    assert first.headers["x-next-offset"] == "2"

    offset = first.headers["x-next-offset"]
    second = await client.get(
        f"/api/aois?source=custom&limit=2&offset={offset}", headers=AUTH
    )
    assert second.status_code == 200, second.text
    assert [r["name"] for r in second.json()] == ["Area C"]
    assert "x-next-offset" not in second.headers


@pytest.mark.asyncio
async def test_invalid_source_returns_422(auth_override, client):
    auth_override("test-user-wri")
    res = await client.get("/api/aois?source=bogus", headers=AUTH)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_protectedareas_alias_accepted(auth_override, client):
    auth_override("test-user-wri")
    # The "protectedareas" alias resolves to the wdpa source.
    res = await client.get("/api/aois?source=protectedareas", headers=AUTH)
    assert res.status_code == 200, res.text
    # Environment-independent: any rows returned must be wdpa.
    assert all(r["source"] == "wdpa" for r in res.json())


@pytest.mark.asyncio
async def test_requires_auth(client):
    res = await client.get("/api/aois?source=custom")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_disputed_rows_excluded_but_still_resolvable(
    auth_override, client
):
    """Search excludes disputed rows, but ``(source, id)`` still finds them."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await _seed_reference_aoi(
        "gadm", "Z01", "Brazilia Disputed", "country", is_disputed=True
    )

    res = await client.get("/api/aois?name=brazil&source=gadm", headers=AUTH)
    assert res.status_code == 200, res.text
    src_ids = [r["src_id"] for r in res.json()]
    assert "BRA" in src_ids
    assert "Z01" not in src_ids

    # Browse mode must also exclude it, not only the similarity path.
    res = await client.get("/api/aois?source=gadm", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["BRA"]

    # The row remains, for a geometry fetch and for the analytics link.
    async with async_session_maker() as session:
        found = await session.scalar(
            text(
                "SELECT name FROM aois "
                "WHERE source = 'gadm' AND source_id = 'Z01'"
            )
        )
    assert found == "Brazilia Disputed"


@pytest.mark.asyncio
async def test_search_ranks_across_sources(auth_override, client):
    """One ranked list holds the reference sources and the caller's own areas."""
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "wdpa", "555", "Amazonia Protected", "protected-area"
    )
    await _seed_reference_aoi(
        "kba", "42", "Amazon Key Area", "key-biodiversity-area"
    )
    await _create_area(client, "Amazon")

    res = await client.get("/api/aois?name=amazon", headers=AUTH)
    assert res.status_code == 200, res.text
    results = res.json()
    assert {r["source"] for r in results} == {"wdpa", "kba", "custom"}
    # An exact match ranks above a longer partial match.
    assert results[0]["name"] == "Amazon"
    assert results[0]["source"] == "custom"


@pytest.mark.asyncio
async def test_browse_orders_by_name_then_source(auth_override, client):
    """Browse mode breaks a tie by (name, source, src_id), over all sources."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("wdpa", "1", "Shared Name", "protected-area")
    await _seed_reference_aoi(
        "kba", "2", "Shared Name", "key-biodiversity-area"
    )
    await _seed_reference_aoi("gadm", "AAA", "Aardvark Land", "country")

    res = await client.get("/api/aois", headers=AUTH)
    assert res.status_code == 200, res.text
    rows = [(r["name"], r["source"]) for r in res.json()]
    assert rows == [
        ("Aardvark Land", "gadm"),
        ("Shared Name", "kba"),
        ("Shared Name", "wdpa"),
    ]


@pytest.mark.asyncio
async def test_reference_sources_are_not_owner_scoped(
    auth_override, client, user_ds
):
    """Only a custom area is owner-scoped. Every reference row is shared."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "IDN", "Indonesia", "country")
    await _create_area(client, "Indonesia Custom")

    auth_override("test-user-ds")
    res = await client.get("/api/aois?name=indonesia", headers=AUTH)
    assert res.status_code == 200, res.text
    sources = [r["source"] for r in res.json()]
    assert sources == ["gadm"]


@pytest.mark.asyncio
async def test_search_is_accent_and_case_insensitive(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm", "BRA.14_1", "Pará, Brazil", "state-province"
    )
    await _seed_reference_aoi(
        "gadm", "BRA.16_1", "Paraná, Brazil", "state-province"
    )

    res = await client.get("/api/aois?name=PARA", headers=AUTH)
    assert res.status_code == 200, res.text
    # The exact leaf ranks first; Paraná follows only as a prefix match.
    assert [r["src_id"] for r in res.json()] == ["BRA.14_1", "BRA.16_1"]


@pytest.mark.asyncio
async def test_parent_in_the_query_disambiguates(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "GBR.1.12_1",
        "Bristol, England, United Kingdom",
        "district-county",
    )
    await _seed_reference_aoi(
        "gadm",
        "USA.22.5_1",
        "Bristol, Massachusetts, United States",
        "district-county",
    )

    res = await client.get("/api/aois?name=Bristol, England", headers=AUTH)
    assert res.status_code == 200, res.text
    src_ids = [r["src_id"] for r in res.json()]
    # Both are exact leaf matches, but only the English one also matches the
    # parent, so it ranks first.
    assert src_ids[0] == "GBR.1.12_1"
    assert "USA.22.5_1" in src_ids


@pytest.mark.asyncio
async def test_a_stored_variant_is_an_exact_match(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "PRT.12_1",
        "Lisboa, Portugal",
        "state-province",
        variants=["Lisbon", "Lissabon"],
    )
    await _seed_reference_aoi(
        "wdpa", "9", "Lisbon, Forest Preserve, USA", "protected-area"
    )

    res = await client.get("/api/aois?name=Lisbon", headers=AUTH)
    assert res.status_code == 200, res.text
    rows = res.json()
    # Both match exactly (one by variant); the admin unit outranks the site.
    assert [r["src_id"] for r in rows] == ["PRT.12_1", "9"]


@pytest.mark.asyncio
async def test_a_token_anywhere_in_the_name_matches(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm", "COD", "Democratic Republic of the Congo", "country"
    )
    await _seed_reference_aoi(
        "gadm", "COG", "Republic of the Congo", "country"
    )
    await _seed_reference_aoi(
        "gadm", "BRA.15.61_2", "Congo, Paraíba, Brazil", "district-county"
    )

    res = await client.get("/api/aois?name=Congo", headers=AUTH)
    assert res.status_code == 200, res.text
    src_ids = [r["src_id"] for r in res.json()]
    # The exact leaf ranks first, then the countries that carry the token.
    assert src_ids[0] == "BRA.15.61_2"
    assert set(src_ids) == {"COD", "COG", "BRA.15.61_2"}


@pytest.mark.asyncio
async def test_a_parent_name_does_not_match_its_children(
    auth_override, client
):
    """The token arm reads the name vector, which holds no parents: a
    country query returns the country, not the thousands of rows under it."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await _seed_reference_aoi(
        "gadm", "BRA.14_1", "Pará, Brazil", "state-province"
    )

    res = await client.get("/api/aois?name=Brazil", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["BRA"]


@pytest.mark.asyncio
async def test_words_spread_over_name_and_parent_still_match(
    auth_override, client
):
    """ "Bristol England" without a comma misses the name vector; the full
    vector is the fallback."""
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "GBR.1.12_1",
        "Bristol, England, United Kingdom",
        "district-county",
    )
    await _seed_reference_aoi(
        "gadm",
        "USA.22.5_1",
        "Bristol, Massachusetts, United States",
        "district-county",
    )

    res = await client.get("/api/aois?name=Bristol England", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["GBR.1.12_1"]


@pytest.mark.asyncio
async def test_a_designation_is_part_of_the_name(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "wdpa",
        "555",
        "Botum Sakor, National Park, Cambodia",
        "protected-area",
        designation="National Park",
    )

    res = await client.get(
        "/api/aois?name=Botum Sakor National Park", headers=AUTH
    )
    assert [r["src_id"] for r in res.json()] == ["555"]


@pytest.mark.asyncio
async def test_a_misspelling_falls_back_to_the_nearest_token(
    auth_override, client
):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm", "IND.16.3_1", "Bangalore, Karnataka, India", "district-county"
    )
    await rebuild_search_tokens()

    res = await client.get("/api/aois?name=Bangalor", headers=AUTH)
    assert res.status_code == 200, res.text
    assert [r["src_id"] for r in res.json()] == ["IND.16.3_1"]


@pytest.mark.asyncio
async def test_a_native_script_name_is_searchable(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "JPN.20_1",
        "Kochi, Japan",
        "state-province",
        variants=["高知県"],
    )

    res = await client.get("/api/aois?name=高知県", headers=AUTH)
    assert res.status_code == 200, res.text
    assert [r["src_id"] for r in res.json()] == ["JPN.20_1"]


async def _autocomplete(client, text_, **params):
    query = "&".join(
        [f"name={text_}", "mode=autocomplete"]
        + [f"{k}={v}" for k, v in params.items()]
    )
    return await client.get(f"/api/aois?{query}", headers=AUTH)


@pytest.mark.asyncio
async def test_autocomplete_completes_a_leaf_prefix_prominent_first(
    auth_override, client
):
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "BGD", "Bangladesh", "country")
    await _seed_reference_aoi(
        "gadm", "IND.16.3_1", "Bangalore, Karnataka, India", "district-county"
    )
    await _seed_reference_aoi(
        "gadm", "THA.1_1", "Bangkok, Thailand", "state-province"
    )
    await _seed_reference_aoi("gadm", "ESP", "Spain", "country")

    res = await _autocomplete(client, "ban")
    assert res.status_code == 200, res.text
    rows = res.json()
    # Country, then state, then district: prominence orders the list.
    assert [r["src_id"] for r in rows] == ["BGD", "THA.1_1", "IND.16.3_1"]
    assert all(0 < r["score"] <= 1 for r in rows)


@pytest.mark.asyncio
async def test_autocomplete_completes_a_variant_and_the_last_word(
    auth_override, client
):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "PRT.12_1",
        "Lisboa, Portugal",
        "state-province",
        variants=["Lisbon"],
    )
    await _seed_reference_aoi(
        "gadm",
        "IND.16.2_1",
        "Bangalore Urban, Karnataka, India",
        "district-county",
    )
    await _seed_reference_aoi(
        "gadm",
        "IND.16.3_1",
        "Bangalore Rural, Karnataka, India",
        "district-county",
    )

    res = await _autocomplete(client, "lisb")
    assert [r["src_id"] for r in res.json()] == ["PRT.12_1"]

    res = await _autocomplete(client, "bangalore ur")
    assert [r["src_id"] for r in res.json()] == ["IND.16.2_1"]


@pytest.mark.asyncio
async def test_autocomplete_filters_by_a_typed_parent(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm", "FRA.8.3_1", "Paris, Île-de-France, France", "district-county"
    )
    await _seed_reference_aoi(
        "gadm",
        "USA.44.2_1",
        "Paris, Lamar, Texas, United States",
        "municipality",
    )

    res = await _autocomplete(client, "par, fr")
    assert [r["src_id"] for r in res.json()] == ["FRA.8.3_1"]


@pytest.mark.asyncio
async def test_autocomplete_rejects_short_input_and_offset(
    auth_override, client
):
    auth_override("test-user-wri")
    assert (await _autocomplete(client, "b")).status_code == 422
    assert (await _autocomplete(client, "ban", offset=2)).status_code == 422


@pytest.mark.asyncio
async def test_autocomplete_keeps_custom_areas_owner_scoped(
    auth_override, client, user_ds
):
    auth_override("test-user-wri")
    await _create_area(client, "Banana Farm")

    res = await _autocomplete(client, "ban")
    assert [r["name"] for r in res.json()] == ["Banana Farm"]

    auth_override("test-user-ds")
    res = await _autocomplete(client, "ban")
    assert res.json() == []


@pytest.mark.asyncio
async def test_input_caps_are_rejected_with_422(auth_override, client):
    auth_override("test-user-wri")
    too_long = "a" * 201
    assert (
        await client.get(f"/api/aois?name={too_long}", headers=AUTH)
    ).status_code == 422
    assert (
        await client.get("/api/aois?name=Par%00is", headers=AUTH)
    ).status_code == 422
    assert (
        await client.get("/api/aois?offset=10001", headers=AUTH)
    ).status_code == 422
    # The core validates the same way the router does: a parent after the
    # comma does not make a one-letter autocomplete valid.
    res = await _autocomplete(client, "a, bcd")
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_correction_is_skipped_for_a_long_phrase(auth_override, client):
    """A phrase of many distinct words is not a typo to correct: the
    correction costs one trigram lookup per word, so it is capped."""
    auth_override("test-user-wri")
    await _seed_reference_aoi("gadm", "BRA", "Brazil", "country")
    await rebuild_search_tokens()

    # Six distinct words, each one edit from "brazil".
    near = ["brasil", "brazl", "brazi", "bazil", "braxil", "brazul"]
    res = await client.get(f"/api/aois?name={' '.join(near)}", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["BRA"]

    res = await client.get(
        f"/api/aois?name={' '.join(near + ['brazill'])}", headers=AUTH
    )
    assert res.status_code == 200
    assert res.json() == []


async def _rebuild_tokens():
    await rebuild_search_tokens()


@pytest.mark.asyncio
async def test_correction_prefers_the_closest_spelling(auth_override, client):
    """ "Paolo" is one edit from "paulo"; a nearer-by-trigram junk token must
    not win, and the typed parent still has to match."""
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm", "BRA.25_1", "São Paulo, Brazil", "state-province"
    )
    await _seed_reference_aoi(
        "gadm", "PAN.1.1_1", "Paola, Bocas del Toro, Panama", "district-county"
    )
    await rebuild_search_tokens()

    res = await client.get("/api/aois?name=Sao Paolo, Brazil", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["BRA.25_1"]


@pytest.mark.asyncio
async def test_correction_does_not_reach_a_distant_word(auth_override, client):
    """ "Kashmir" is two edits from "kashmore" on seven letters: not a typo."""
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "gadm",
        "PAK.8.12_1",
        "Kashmore, Larkana, Sindh, Pakistan",
        "district-county",
    )
    await rebuild_search_tokens()

    res = await client.get("/api/aois?name=Kashmir", headers=AUTH)
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_an_extra_generic_word_is_dropped(auth_override, client):
    auth_override("test-user-wri")
    await _seed_reference_aoi(
        "wdpa", "916", "Serengeti, National Park, TZA", "protected-area"
    )
    await _seed_reference_aoi(
        "gadm", "CZE", "Czechia", "country", variants=["Czech Republic"]
    )
    await rebuild_search_tokens()

    res = await client.get("/api/aois?name=Serengeti NP", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["916"]
    # The whole phrase is a stored variant, so it is an exact match first.
    res = await client.get("/api/aois?name=Czech Republic", headers=AUTH)
    assert [r["src_id"] for r in res.json()] == ["CZE"]
