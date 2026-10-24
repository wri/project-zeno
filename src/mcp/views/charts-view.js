// curated_charts: each of GNW's charts as an insight card, with the curated
// caption, the Chart / Table toggle, the generator that drew it and the
// pull it comes from.

function chartCard(chart, data) {
  // The server says when it held the values back; an empty chart is empty.
  const withheld = Boolean(data.withheld);
  const empty = !withheld && !(chart.chart_data || []).length;
  return panel({
    iconName: chart.chart_type === "pie" ? "chartPie" : chart.chart_type === "table" ? "table" : "chartBar",
    title: chart.title,
    children: [
      curatedCaption(),
      withheld
        ? note("info", "GNW shows this chart's values in its own app only.")
        : empty
          ? h("div", { class: "empty" }, "No data to chart for these dates and areas.")
          : chartWithTable(chart),
    ],
  });
}

function render(data, args) {
  const charts = data.charts || [];
  const generator = data.generator || {};
  return h(
    "div",
    { style: { display: "flex", flexDirection: "column", gap: "12px" } },
    h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: "6px" } },
      h("span", { class: "eyebrow", style: { color: "var(--label-data)" } }, data.dataset_name),
      pullMeta(data),
      clampNote(data, args)
    ),
    charts.length
      ? charts.map((chart) => chartCard(chart, data))
      : note("info", "The pull returned no data to chart."),
    reproducePanel(data),
    provenanceFooter(
      data,
      generator.code_url &&
        h(
          "span",
          {},
          "Drawn by ",
          linkButton(generator.name, generator.code_url, "code")
        )
    )
  );
}

mountView({
  pending: (args) =>
    loading(`Drawing GNW's charts for ${(args.aoi_ids || []).join(", ")}…`),
  render,
});
