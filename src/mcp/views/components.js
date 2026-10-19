// Shared pieces of the views: an element builder, icons, the number and label
// formatting of project-zeno-next (utils/formatCharts.tsx), and the panel,
// card, table and footer patterns its components use.

function h(tag, attrs, ...children) {
  const svg = tag.startsWith("svg:");
  const el = svg
    ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4))
    : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      el.setAttribute("class", value);
    } else if (key === "style" && typeof value === "object") {
      Object.assign(el.style, value);
    } else if (key === "text") {
      el.textContent = value;
    } else {
      el.setAttribute(key, value === true ? "" : value);
    }
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(child));
  }
  return el;
}

// Icons drawn on a 16px grid in the stroke style of Phosphor regular.
const ICON_PATHS = {
  polygon: "M3 6.5 7.5 2.5 13 5 12 12 5 13.5Z",
  pin: "M8 14s4.5-4 4.5-7.5a4.5 4.5 0 0 0-9 0C3.5 10 8 14 8 14Zm0-6a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
  database:
    "M8 6c2.8 0 5-.9 5-2s-2.2-2-5-2-5 .9-5 2 2.2 2 5 2Zm-5-2v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2",
  chartBar: "M2 13.5h12M4 13.5V8h2.5v5.5M6.5 13.5V4.5H9v9M9 13.5V7h2.5v6.5",
  chartPie: "M8 2v6l5.2 3A6 6 0 1 1 8 2Zm0 0a6 6 0 0 1 5.2 9",
  table: "M2 3.5h12v9H2Zm0 3h12M2 9.5h12M6 6.5v6",
  calendar: "M3 3.5h10v10H3Zm0 3h10M5.5 2v3M10.5 2v3",
  layers: "M8 2 14 5.5 8 9 2 5.5Zm-6 6L8 11.5 14 8M2 10.5 8 14l6-3.5",
  external: "M9 2.5h4.5V7M13.5 2.5 7.5 8.5M12 9.5v4H2.5V4h4",
  code: "M5 4.5 1.5 8 5 11.5M11 4.5 14.5 8 11 11.5M9.5 2.5l-3 11",
  check: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM5.5 8.2l1.8 1.8 3.4-3.6",
  warning: "M8 2 14.5 13.5h-13ZM8 6.5v3M8 11.6v.1",
  info: "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM8 7.5V11M8 5v.1",
  arrowRight: "M2.5 8h11M9.5 4l4 4-4 4",
  question:
    "M8 14.5a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13ZM6.2 6.2A1.9 1.9 0 0 1 8 4.8c1 0 1.9.7 1.9 1.7 0 1.5-1.9 1.6-1.9 3M8 11.5v.1",
  magnifier: "M7 12a5 5 0 1 0 0-10 5 5 0 0 0 0 10Zm3.5-1.5L14 14",
};

function icon(name, size = 14) {
  return h(
    "svg:svg",
    {
      class: "icon",
      width: size,
      height: size,
      viewBox: "0 0 16 16",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": 1.3,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
    },
    h("svg:path", { d: ICON_PATHS[name] })
  );
}

// ---- Formatting (utils/formatCharts.tsx) -----------------------------------

const UNIT_PATTERNS = [
  [/(_tco2e_per_tonne)$/i, "tCO₂e/t"],
  [/(_mgco2e)$/i, "MgCO₂e"],
  [/(_tco2e)$/i, "tCO₂e"],
  [/(_co2e)$/i, "CO₂e"],
  [/(_km2|_km²)$/i, "km²"],
  [/(_ha)$/i, "ha"],
  [/(_mt)$/i, "Mt"],
  [/(_tonnes|_t)$/i, "t"],
  [/(_pct|_percent|_%|_percentage)$/i, "%"],
];

/** "carbon_emissions_MgCO2e" → "Carbon emissions (MgCO₂e)". */
function toAxisLabel(key) {
  if (!key) return "";
  let label = String(key);
  let unit = "";
  for (const [pattern, unitText] of UNIT_PATTERNS) {
    if (pattern.test(label)) {
      label = label.replace(pattern, "");
      unit = unitText;
      break;
    }
  }
  label = label
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
  if (label) label = label[0].toUpperCase() + label.slice(1).toLowerCase();
  return unit ? `${label} (${unit})` : label;
}

/** The unit of a column, from its name: "area_ha" → "ha". */
function unitOf(key) {
  for (const [pattern, unitText] of UNIT_PATTERNS) {
    if (pattern.test(String(key || ""))) return unitText;
  }
  return "";
}

function isYearKey(key) {
  return /(^|_)year$/i.test(String(key || ""));
}

/** Compact numbers for axis ticks: 1234567 → "1.2M". */
function formatCompact(value, key) {
  if (isYearKey(key)) return String(value);
  const num = Number(value);
  if (num === 0) return "0";
  if (!Number.isFinite(num)) return String(value);
  if (Math.abs(num) < 1000) {
    return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  for (const [divisor, suffix] of [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ]) {
    const scaled = Math.round((num / divisor) * 10) / 10;
    if (Math.abs(scaled) >= 1) {
      return `${scaled.toFixed(1).replace(/\.0$/, "")}${suffix}`;
    }
  }
  return String(num);
}

/** Full-precision numbers for tooltips and tables: "1,234,567.89". */
function formatFull(value, key) {
  if (isYearKey(key)) return String(value);
  if (value === null || value === undefined || value === "") return "";
  const num = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(num)) return String(value);
  return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** "26%" for most slices, "<1%" for slivers. */
function formatShare(value, total) {
  if (!total || total <= 0 || !Number.isFinite(value)) return "";
  const pct = (value / total) * 100;
  if (pct > 0 && pct < 1) return "<1%";
  return `${Math.round(pct)}%`;
}

function formatDate(value) {
  if (!value) return "";
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
  if (!match) return String(value);
  const date = new Date(Date.UTC(+match[1], +match[2] - 1, +match[3]));
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function formatRange(start, end) {
  if (!start && !end) return "";
  return `${formatDate(start)} – ${formatDate(end)}`;
}

function isNumeric(value) {
  return (
    typeof value === "number" ||
    (typeof value === "string" && value.trim() !== "" && !isNaN(Number(value)))
  );
}

// ---- Data helpers -----------------------------------------------------------

// Columns that identify a row rather than measure something.
const ID_COLUMNS = new Set(["aoi_id", "aoi_type"]);

function columnsOf(rows) {
  const columns = [];
  const seen = new Set();
  for (const row of rows || []) {
    for (const key of Object.keys(row || {})) {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    }
  }
  return columns;
}

/** The columns worth showing: no ids, and no area name for a single area. */
function displayColumns(rows) {
  const columns = columnsOf(rows).filter((key) => !ID_COLUMNS.has(key));
  const names = new Set((rows || []).map((row) => row.name));
  const shown = names.size > 1 ? columns : columns.filter((k) => k !== "name");
  // The area name reads best first.
  return shown.includes("name")
    ? ["name", ...shown.filter((k) => k !== "name")]
    : shown;
}

// ---- Pieces -----------------------------------------------------------------

function panel({ iconName, title, count, children, headerExtra }) {
  return h(
    "section",
    { class: "panel" },
    h(
      "header",
      { class: "panel-header" },
      iconName && icon(iconName, 16),
      h("h2", { title }, title),
      count !== undefined && h("span", { class: "count" }, count),
      h("span", { class: "spacer" }),
      headerExtra
    ),
    h("div", { class: "panel-body" }, children)
  );
}

function note(kind, text) {
  const iconName = { warning: "warning", error: "warning", info: "info" }[kind];
  return h(
    "div",
    { class: `note ${kind}`, role: kind === "error" ? "alert" : undefined },
    icon(iconName, 14),
    h("div", {}, text)
  );
}

function chip(iconName, text, title) {
  return h(
    "span",
    { class: "chip", title: title || text },
    iconName && icon(iconName, 12),
    text
  );
}

function linkButton(text, url, iconName = "external") {
  return h(
    "button",
    {
      class: "link",
      type: "button",
      title: url,
      onClick: () => Bridge.openLink(url),
    },
    text,
    icon(iconName, 11)
  );
}

const CURATED_NOTE =
  "This analysis was produced from a verified, direct data query rather than generated by AI, so its charts and figures come straight from the source data.";

function curatedCaption() {
  return h(
    "span",
    { class: "eyebrow curated", title: CURATED_NOTE },
    icon("check", 12),
    "Curated · GNW chart"
  );
}

function dataTable(rows, { columns, caption } = {}) {
  const keys = columns || displayColumns(rows);
  const numeric = new Set(
    keys.filter(
      (key) =>
        !isYearKey(key) &&
        rows.some((row) => isNumeric(row[key])) &&
        rows.every((row) => row[key] === null || isNumeric(row[key]))
    )
  );
  return h(
    "div",
    { class: "table-wrap", tabindex: 0 },
    h(
      "table",
      {},
      caption && h("caption", { class: "sr-only" }, caption),
      h(
        "thead",
        {},
        h(
          "tr",
          {},
          keys.map((key) =>
            h(
              "th",
              { class: numeric.has(key) ? "n" : undefined, scope: "col" },
              key === "name" ? "Area" : toAxisLabel(key)
            )
          )
        )
      ),
      h(
        "tbody",
        {},
        rows.map((row) =>
          h(
            "tr",
            {},
            keys.map((key) =>
              h(
                "td",
                { class: numeric.has(key) ? "n" : undefined },
                numeric.has(key) ? formatFull(row[key], key) : row[key] ?? ""
              )
            )
          )
        )
      )
    )
  );
}

/** Areas, dates and options of a pull, as chips. */
function pullMeta(data) {
  const areas = data.areas || [];
  const shownAreas = areas.slice(0, 4);
  return h(
    "div",
    { class: "meta" },
    shownAreas.map((area) =>
      chip("pin", area.name, `${area.name} · ${area.aoi_id}`)
    ),
    areas.length > shownAreas.length &&
      chip(null, `+${areas.length - shownAreas.length} more`),
    (data.start_date || data.end_date) &&
      chip("calendar", formatRange(data.start_date, data.end_date)),
    data.context_layer &&
      chip("layers", toAxisLabel(data.context_layer), "Context layer"),
    data.canopy_cover !== null &&
      data.canopy_cover !== undefined &&
      chip(null, `Canopy ≥ ${data.canopy_cover}%`, "Canopy cover threshold")
  );
}

function clampNote(data, args) {
  if (!data.date_range_clamped) return null;
  const asked = formatRange(args?.start_date, args?.end_date);
  return note(
    "warning",
    `The dates were fitted to what the dataset covers: ${formatRange(
      data.start_date,
      data.end_date
    )}${asked ? ` (asked for ${asked})` : ""}.`
  );
}

function provenanceFooter(data, extra) {
  return h(
    "div",
    { class: "footer" },
    extra,
    data.source_url && linkButton("Analytics result", data.source_url),
    data.result_id &&
      h("span", { class: "mono", title: "Analytics result id" }, data.result_id)
  );
}

function loading(text) {
  return h(
    "div",
    { class: "panel" },
    h(
      "div",
      { class: "loading", role: "status" },
      h("span", {}, text),
      h("span", { class: "skeleton" })
    )
  );
}

/** The text a tool returned, for errors and results without structure. */
function resultText(result) {
  return (result.content || [])
    .filter((part) => part.type === "text")
    .map((part) => part.text)
    .join("\n")
    .trim();
}

/**
 * Wire a view to the host: show `pending(args)` while the tool runs, then
 * `render(data, args, result)`; an error result shows its message.
 */
function mountView({ pending, render }) {
  const root = document.getElementById("app");
  let args = {};
  const show = (node) => root.replaceChildren(node);
  Bridge.start({
    onInput(input) {
      args = input;
      if (pending) show(pending(args));
    },
    onResult(result) {
      try {
        if (result.isError) {
          show(note("error", resultText(result) || "The tool failed."));
          return;
        }
        show(render(result.structuredContent || {}, args, result));
      } catch (error) {
        console.error(error);
        show(note("error", `This view could not draw the result: ${error}`));
      }
    },
    onCancel() {
      show(note("info", "The call was cancelled."));
    },
  });
}
