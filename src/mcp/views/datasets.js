// list_datasets and get_dataset: the catalog as DatasetCards, and one
// dataset's details with its coverage, options, colors and cautions.

const DETAIL_SECTIONS = [
  ["description", "Description", false],
  ["presentation_instructions", "How to present it", false],
  ["methodology", "Methodology", false],
  ["citation", "Citation", false],
  ["license", "License", false],
];

function datasetCard(ds, onOpen) {
  const options = [
    ds.context_layers?.length && `${ds.context_layers.length} context layers`,
    ds.parameters?.length && ds.parameters.map(toAxisLabel).join(", "),
  ].filter(Boolean);
  const card = h(
    "div",
    {
      class: "card",
      role: "button",
      tabindex: 0,
      "aria-label": `Show ${ds.dataset_name}`,
      title: ds.card,
      style: { height: "auto", minHeight: "80px", alignItems: "stretch" },
    },
    h(
      "div",
      { class: "thumb", style: { height: "auto", minHeight: "80px" } },
      h("span", { class: "num", style: { fontSize: "18px", color: "var(--fg-muted)" } }, ds.dataset_id)
    ),
    h(
      "div",
      { class: "card-text", style: { padding: "8px 36px 8px 16px" } },
      h(
        "span",
        { class: "eyebrow", style: { color: "var(--label-data)" } },
        "Data",
        ds.curated_charts && h("span", { class: "muted" }, " · curated charts")
      ),
      h("span", { class: "card-title" }, ds.dataset_name),
      h("span", { class: "card-desc wrap" }, cardSummary(ds)),
      options.length > 0 && h("span", { class: "card-desc" }, options.join(" · "))
    ),
    h("span", { class: "arrow" }, icon("arrowRight", 18))
  );
  const open = () => onOpen(ds, card);
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return card;
}

/** The card text without the leading "Name (years)." the title repeats. */
function cardSummary(ds) {
  const card = ds.card || "";
  const stop = card.indexOf(". ");
  return stop > 0 && stop < 90 ? card.slice(stop + 2) : card;
}

function renderList(data) {
  const datasets = data.datasets || [];
  const root = h("div", { style: { display: "flex", flexDirection: "column", gap: "12px" } });
  const detail = h("div", {});
  const open = async (ds, card) => {
    detail.replaceChildren(loading(`Reading ${ds.dataset_name}…`));
    detail.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
    try {
      const result = await Bridge.callTool("get_dataset", { dataset_id: ds.dataset_id });
      detail.replaceChildren(
        result.isError
          ? note("error", resultText(result))
          : renderDetail(result.structuredContent || {})
      );
    } catch {
      // The host does not proxy tool calls: ask in the chat instead.
      detail.replaceChildren();
      const sent = await Bridge.sendMessage(`Tell me about dataset ${ds.dataset_id}, ${ds.dataset_name}.`);
      if (sent) card.classList.add("sent");
    }
  };
  root.append(
    panel({
      iconName: "database",
      title: "Global Nature Watch datasets",
      count: `${datasets.length} datasets`,
      children: h("div", { class: "cards" }, datasets.map((ds) => datasetCard(ds, open))),
    }),
    detail
  );
  return root;
}

function fact(label, value) {
  if (!value) return null;
  return h("div", { class: "fact" }, h("span", { class: "eyebrow" }, label), h("span", { class: "value" }, value));
}

function section(title, content, open = false) {
  if (!content) return null;
  return h("details", { class: "section", open }, h("summary", {}, title), content);
}

function colorSwatches(colors) {
  if (!colors) return null;
  const entries = [
    ...(colors.categories || []).map((c) => [c.label_en || c.slug, c.color]),
    colors.series_color && ["Series", colors.series_color],
    colors.divergent_colors?.positive && ["Positive", colors.divergent_colors.positive],
    colors.divergent_colors?.negative && ["Negative", colors.divergent_colors.negative],
  ].filter((entry) => entry && entry[1]);
  if (!entries.length) return null;
  return h(
    "div",
    { class: "swatches" },
    entries.map(([label, color]) =>
      h("span", {}, h("span", { class: "swatch", style: { background: color } }), label, h("span", { class: "mono" }, color))
    )
  );
}

// Cautions longer than this show their start, with a toggle for the rest.
const CAUTION_PREVIEW_CHARS = 280;

function cautionsNote(text) {
  if (text.length <= CAUTION_PREVIEW_CHARS) return note("warning", text);
  const cut = text.lastIndexOf(" ", CAUTION_PREVIEW_CHARS);
  const body = h("span", {}, `${text.slice(0, cut)}… `);
  const toggle = h("button", { class: "link", type: "button", "aria-expanded": "false" }, "Read all cautions");
  let open = false;
  toggle.addEventListener("click", () => {
    open = !open;
    body.textContent = open ? `${text} ` : `${text.slice(0, cut)}… `;
    toggle.textContent = open ? "Show less" : "Read all cautions";
    toggle.setAttribute("aria-expanded", String(open));
  });
  const element = note("warning", "");
  element.lastChild.replaceChildren(h("strong", {}, "Cautions. "), body, toggle);
  return element;
}

function renderDetail(ds) {
  const layers = ds.context_layers || [];
  const params = ds.parameters || [];
  return panel({
    iconName: "database",
    title: ds.dataset_name,
    count: `dataset ${ds.dataset_id}`,
    children: [
      ds.curated_charts && curatedCaption(),
      h("div", { class: "muted" }, ds.card),
      h(
        "div",
        { class: "facts" },
        fact("Coverage", formatRange(ds.start_date, ds.end_date || "today")),
        fact("Content", ds.content_date),
        fact("Resolution", ds.resolution),
        fact("Updated", ds.update_frequency),
        fact("Extent", ds.geographic_coverage)
      ),
      ds.cautions && cautionsNote(ds.cautions),
      section(
        "Context layers",
        layers.length &&
          h(
            "ul",
            { class: "option-list" },
            layers.map((layer) => h("li", {}, h("code", {}, layer.value), " ", layer.description))
          ),
        true
      ),
      section(
        "Parameters",
        params.length &&
          h(
            "ul",
            { class: "option-list" },
            params.map((param) =>
              h(
                "li",
                {},
                h("code", {}, param.name),
                " ",
                param.description,
                param.values && h("span", { class: "muted" }, ` One of: ${[].concat(param.values).join(", ")}.`)
              )
            )
          ),
        true
      ),
      section("Colors", colorSwatches(ds.colors)),
      DETAIL_SECTIONS.map(([key, title, open]) =>
        section(title, ds[key] && h("p", { class: "prose" }, ds[key]), open)
      ),
    ],
  });
}

mountView({
  pending: (args) =>
    loading(args.dataset_id ? `Reading dataset ${args.dataset_id}…` : "Reading the catalog…"),
  render: (data) => ("datasets" in data ? renderList(data) : renderDetail(data)),
});
