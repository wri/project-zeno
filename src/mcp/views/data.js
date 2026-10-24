// pull_data: the rows of a pull as a table, with a quick chart when the rows
// are a series over years or dates, and the pull's areas, dates, options
// and provenance.

// Column names of measures, as the analytics API names them.
const MEASURE_KEY = /(^|_)(area|ha|value|count|alerts?|emissions?|flux|loss|gain|tco2e?|mgco2e?)(_|$)/i;

/** A bar or line chart spec for rows over time, or null. */
function quickChart(rows, data) {
  if (!rows.length) return null;
  const columns = columnsOf(rows).filter((key) => !ID_COLUMNS.has(key));
  const x = columns.find((key) => TIME_KEY.test(key));
  if (!x) return null;
  const numeric = columns.filter(
    (key) => key !== x && key !== "name" && rows.every((row) => row[key] === null || isNumeric(row[key]))
  );
  // A measure (an area, a count, an amount) over a numeric dimension such as
  // a threshold or a class code, which comes first in some results.
  const value = numeric.find((key) => MEASURE_KEY.test(key)) || numeric[0];
  if (!value) return null;
  const points = new Set(rows.map((row) => row[x])).size;
  return {
    title: `${toAxisLabel(value)} by ${toAxisLabel(x).toLowerCase()}`,
    chart_type: points > 40 ? "line" : "bar",
    x_axis: x,
    y_axis: value,
    series_fields: [],
    chart_data: rows,
    color_map: {},
  };
}

function render(data, args) {
  const rows = data.rows || [];
  const chartSpec = quickChart(rows, data);
  let body;
  if (data.withheld) {
    body = note("info", "The rows of this dataset are shown as curated charts only. Use curated_charts.");
  } else if (!rows.length) {
    body = h("div", { class: "empty" }, "The pull returned no rows.");
  } else if (chartSpec) {
    body = [
      h(
        "span",
        {
          class: "eyebrow",
          title: "Drawn by this view from the first time and value columns. GNW's own charts come from curated_charts.",
        },
        "Quick look · not a GNW chart"
      ),
      chartWithTable(chartSpec, { tableRows: rows }),
    ];
  } else {
    body = dataTable(rows, { caption: data.dataset_name });
  }
  const dataPanel = panel({
    iconName: "table",
    title: data.dataset_name,
    count: `${formatFull(data.row_count)} rows`,
    children: [
      pullMeta(data),
      clampNote(data, args),
      body,
      data.rows_truncated &&
        note("info", `Showing the first ${formatFull(rows.length)} of ${formatFull(data.row_count)} rows.`),
      provenanceFooter(data),
    ],
  });
  return h(
    "div",
    { style: { display: "flex", flexDirection: "column", gap: "12px" } },
    dataPanel,
    reproducePanel(data)
  );
}

mountView({
  pending: (args) => loading(`Pulling data for ${(args.aoi_ids || []).join(", ")}…`),
  render,
});
