// resolve_areas and search_areas: the selected areas as AreaCards, the
// candidates of an ambiguous name as cards the user can pick from, and
// search matches as cards that tell the chat which area to use.

const SOURCE_LABELS = {
  gadm: "Administrative area",
  kba: "Key biodiversity area",
  wdpa: "Protected area",
  landmark: "Indigenous territory",
  oil_palm: "Oil palm concession",
  rspo_oil_palm: "RSPO oil palm concession",
  logging: "Logging concession",
  mining: "Mining concession",
  wood_fiber: "Wood fiber concession",
};

const SUBTYPE_LABELS = {
  country: "Country",
  "state-province": "State / province",
  "district-county": "District / county",
  municipality: "Municipality",
  locality: "Locality",
  neighbourhood: "Neighbourhood",
  "protected-area": "Protected area",
  "key-biodiversity-area": "Key biodiversity area",
  "indigenous-and-community-land": "Indigenous and community land",
};

// Above this many areas, a compact list replaces the cards.
const MAX_CARDS = 6;
const LIST_PREVIEW = 12;

function subtypeLabel(area) {
  return SUBTYPE_LABELS[area.subtype] || toAxisLabel(area.subtype || "");
}

function areaCard(area, { onPick } = {}) {
  const text = h(
    "div",
    { class: "card-text" },
    h(
      "span",
      { class: "eyebrow", style: { color: "var(--label-area)" } },
      SOURCE_LABELS[area.source] || area.source
    ),
    h("span", { class: "card-title", title: area.name }, area.name),
    h(
      "span",
      { class: "card-desc" },
      [subtypeLabel(area), area.aoi_id].filter(Boolean).join(" · "),
      area.corrected &&
        h("span", { class: "badge-warn" }, " · spelling corrected")
    )
  );
  const card = h(
    "div",
    { class: "card", title: `${area.name} · ${area.aoi_id}` },
    h("div", { class: "thumb" }, icon(area.source === "gadm" ? "polygon" : "pin", 28)),
    text
  );
  if (onPick) {
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label", `Use ${area.name}`);
    card.append(h("span", { class: "arrow" }, icon("arrowRight", 18)));
    const pick = async () => {
      const sent = await onPick(area);
      if (sent) {
        card.classList.add("sent");
        card.querySelector(".arrow").replaceChildren(icon("check", 18));
      }
    };
    card.addEventListener("click", pick);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        pick();
      }
    });
  }
  return card;
}

function areaList(areas) {
  const list = h("div", { class: "rows", role: "list", style: { alignSelf: "stretch" } });
  const fill = (count) =>
    list.replaceChildren(
      ...areas.slice(0, count).map((area) =>
        h(
          "div",
          { class: "row", role: "listitem" },
          h("span", { class: "name", title: area.name }, area.name),
          h("span", { class: "id" }, area.aoi_id)
        )
      )
    );
  fill(LIST_PREVIEW);
  if (areas.length <= LIST_PREVIEW) return list;
  const more = h(
    "button",
    { class: "btn", type: "button" },
    `Show all ${areas.length}`
  );
  more.addEventListener("click", () => {
    fill(areas.length);
    more.remove();
  });
  return h("div", { style: { display: "flex", flexDirection: "column", gap: "8px", alignItems: "flex-start" } }, list, more);
}

function areasBlock(areas, options) {
  if (areas.length > MAX_CARDS && !options?.onPick) return areaList(areas);
  return h("div", { class: "cards" }, areas.map((area) => areaCard(area, options)));
}

function sourceSummary(areas) {
  const counts = {};
  for (const area of areas) {
    const key = subtypeLabel(area) || SOURCE_LABELS[area.source];
    counts[key] = (counts[key] || 0) + 1;
  }
  return h(
    "div",
    { class: "meta" },
    Object.entries(counts).map(([label, count]) => chip(null, `${count} × ${label}`))
  );
}

function pickArea(area) {
  return Bridge.sendMessage(`Use ${area.name} (${area.aoi_id}).`);
}

function placesOf(args) {
  return (args.places || []).map((place) => place.place).filter(Boolean);
}

function renderResolve(data, args, result) {
  const places = placesOf(args).join("; ");
  if (data.candidates?.length) {
    return panel({
      iconName: "question",
      title: `Which ${places || "place"} do you mean?`,
      count: `${data.candidates.length} matches`,
      children: [
        h(
          "div",
          { class: "muted" },
          "The name matches places in more than one country. Pick one to tell the chat."
        ),
        areasBlock(data.candidates, { onPick: pickArea }),
      ],
    });
  }
  if (!data.areas?.length) {
    return panel({
      iconName: "magnifier",
      title: places ? `No areas selected for ${places}` : "No areas selected",
      children: note("info", resultText(result) || "No area was selected."),
    });
  }
  // The geocoder's notes follow the list: places it could not match.
  const notes = resultText(result).split("\n\n").slice(1).join("\n\n").trim();
  return panel({
    iconName: "polygon",
    title: data.selection_name,
    count: data.areas.length === 1 ? "1 area" : `${data.areas.length} areas`,
    children: [
      args.subregion && data.areas.length > 1 && sourceSummary(data.areas),
      areasBlock(data.areas),
      notes && note("warning", notes),
    ],
  });
}

function renderSearch(data, args) {
  const areas = data.areas || [];
  const title = args.name ? `Areas matching “${args.name}”` : "Matching areas";
  if (!areas.length) {
    return panel({
      iconName: "magnifier",
      title,
      children: note("info", "No area matches. Try a broader name (the country or region) or another spelling."),
    });
  }
  return panel({
    iconName: "magnifier",
    title,
    count: `${areas.length} best first`,
    children: [
      h("div", { class: "muted" }, "Pick an area to tell the chat which one to use."),
      areasBlock(areas, { onPick: pickArea }),
    ],
  });
}

mountView({
  pending: (args) =>
    loading(
      args.name
        ? `Searching areas for “${args.name}”…`
        : `Finding ${placesOf(args).join("; ") || "areas"}…`
    ),
  render: (data, args, result) =>
    "selection_name" in data
      ? renderResolve(data, args, result)
      : renderSearch(data, args),
});
