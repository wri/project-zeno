// pull_data: the rows of a pull as a table, with a quick chart when the rows
// are a series over years or dates, and the pull's areas, dates, options
// and provenance.

const TIME_KEY = /(^|_)(year|date)$/i;

/** A bar or line chart spec for rows over time, or null. */
function quickChart(rows, data) {
  if (!rows.length) return null;
  const columns = columnsOf(rows).filter((key) => !ID_COLUMNS.has(key));
  const x = columns.find((key) => TIME_KEY.test(key));
  if (!x) return null;
  const value = columns.find(
    (key) => key !== x && key !== "name" && rows.every((row) => row[key] === null || isNumeric(row[key]))
  );
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
  if (!rows.length && data.row_count) {
    body = note("info", "The rows of this dataset are shown as curated charts only. Use curated_charts.");
  } else if (!rows.length) {
    body = h("div", { class: "empty" }, "The pull returned no rows.");
  } else if (chartSpec) {
    body = chartWithTable(chartSpec, { tableRows: rows });
  } else {
    body = dataTable(rows, { caption: data.dataset_name });
  }
  return panel({
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
}

mountView({
  pending: (args) => loading(`Pulling data for ${(args.aoi_ids || []).join(", ")}…`),
  render,
});
