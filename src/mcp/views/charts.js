// SVG charts for the InsightChart spec (chart_type, x_axis, y_axis,
// series_fields, stack/group/color fields, color_map, series_color,
// divergent_colors, chart_data), drawn the way ChartWidget.tsx draws them
// with recharts: dashed horizontal grid, compact ticks, top-rounded bars,
// a donut with its total in the centre and a legend with shares.

// ChartColors.tsx order: blue, orange, green, pink, cyan, red, purple,
// yellow, mint, berenjena (colorblind-safe neighbours).
const PALETTE = [
  "#3b82f6",
  "#ff9916",
  "#00a651",
  "#f26798",
  "#01b9f3",
  "#ff452c",
  "#ba4aff",
  "#ffd80b",
  "#00dca7",
  "#895277",
];
const DASHES = ["", "6 3", "2 3", "8 3 2 3"];
const TICK_FONT_PX = 11;
const CHAR_PX = 6.5;
const TICK_MARGIN = 6;
const TITLE_BAND = 18;
const CHART_HEIGHT = 260;
const MAX_LINE_DOTS = 14;
const STACKED_TYPES = new Set(["stacked-bar", "stacked-bar-with-line", "area"]);

let measureContext = null;

/** The width of a tick label in the chart font; the estimate when the
 * canvas is unavailable. */
function textWidth(text) {
  measureContext = measureContext || document.createElement("canvas").getContext("2d");
  if (!measureContext) return text.length * CHAR_PX;
  measureContext.font = `${TICK_FONT_PX}px ${getComputedStyle(document.body).fontFamily}`;
  return measureContext.measureText(text).width;
}

function niceStep(range, count) {
  const raw = range / Math.max(count, 1);
  const power = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function niceTicks(min, max, count = 5) {
  if (min === max) max = min + 1;
  const step = niceStep(max - min, count);
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = start; v <= end + step / 2; v += step) {
    ticks.push(Math.abs(v) < step / 1e6 ? 0 : v);
  }
  return ticks;
}

function distinct(values) {
  const seen = new Set();
  const out = [];
  for (const value of values) {
    const key = String(value);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(value);
    }
  }
  return out;
}

// A column over time: its values are put in order on the x axis.
const TIME_KEY = /(^|_)(year|date)$/i;

/** The x categories in order: numbers and dates ascending, so a series
 * whose first area starts later than another's still runs left to right;
 * anything else in the order the rows give it. */
function orderCategories(categories, x) {
  if (categories.every((value) => isNumeric(value))) {
    return [...categories].sort((a, b) => Number(a) - Number(b));
  }
  if (TIME_KEY.test(x)) {
    return [...categories].sort((a, b) => String(a).localeCompare(String(b)));
  }
  return categories;
}

/** Turn a chart spec into categories and series of values per category. */
function cartesianModel(spec) {
  const rows = spec.chart_data || [];
  const type = spec.chart_type;
  const x = spec.x_axis || columnsOf(rows)[0];
  const categories = orderCategories(distinct(rows.map((row) => row[x])), x);
  const repeatsX = categories.length < rows.length;
  const names = distinct(rows.map((row) => row.name));
  // One series per value of the stack/group/colour field; several areas
  // with the same x values become one series per area.
  const pivot =
    spec.stack_field ||
    spec.group_field ||
    spec.color_field ||
    (repeatsX && names.length > 1 && !spec.series_fields?.length ? "name" : "");

  let series;
  if (pivot && spec.y_axis) {
    series = distinct(rows.map((row) => row[pivot])).map((value) => ({
      key: String(value),
      label: String(value),
      match: (row) => String(row[pivot]) === String(value),
      field: spec.y_axis,
    }));
  } else {
    const keys = spec.series_fields?.length
      ? spec.series_fields
      : [spec.y_axis || columnsOf(rows).find((k) => k !== x && isNumeric(rows[0]?.[k]))];
    series = keys.map((key) => ({
      key,
      label: toAxisLabel(key),
      match: () => true,
      field: key,
    }));
  }

  const single = series.length === 1;
  series.forEach((s, i) => {
    s.color =
      spec.color_map?.[s.key] ||
      (single && (spec.divergent_colors?.positive || spec.series_color)) ||
      PALETTE[i % PALETTE.length];
    s.dash = type === "line" || type === "area" ? DASHES[i % DASHES.length] : "";
    s.values = categories.map((category) => {
      let total = null;
      for (const row of rows) {
        if (String(row[x]) !== String(category) || !s.match(row)) continue;
        const value = Number(row[s.field]);
        if (Number.isFinite(value)) total = (total ?? 0) + value;
      }
      return total;
    });
  });

  const yKey = series.length === 1 ? series[0].field : spec.y_axis;
  return {
    type,
    x,
    yKey,
    categories,
    series,
    stacked: STACKED_TYPES.has(type) && series.length > 1,
    divergent: single && type.includes("bar") ? spec.divergent_colors : null,
  };
}

function tooltipBox() {
  return h("div", { class: "tooltip", hidden: true, role: "presentation" });
}

function placeTooltip(tip, container, clientX, clientY) {
  const box = container.getBoundingClientRect();
  tip.hidden = false;
  const tipBox = tip.getBoundingClientRect();
  let left = clientX - box.left + 12;
  if (left + tipBox.width > box.width) left = clientX - box.left - tipBox.width - 12;
  let top = clientY - box.top - tipBox.height / 2;
  top = Math.max(0, Math.min(top, box.height - tipBox.height));
  tip.style.left = `${Math.max(0, left)}px`;
  tip.style.top = `${top}px`;
}

function tooltipRows(title, entries, key) {
  return [
    h("div", { class: "t-title" }, title),
    entries.map((entry) =>
      h(
        "div",
        { class: "t-row" },
        h("span", { class: "dot", style: { background: entry.color } }),
        h("span", {}, entry.label),
        h("span", { class: "num" }, formatFull(entry.value, key))
      )
    ),
  ];
}

/** Rectangle with the top (or, for negatives, bottom) corners rounded. */
function barPath(x, y, w, hgt, radius, down) {
  const r = Math.min(radius, w / 2, hgt);
  if (r <= 0 || hgt <= 0) return `M${x},${y}h${w}v${hgt}h${-w}Z`;
  if (down) {
    return `M${x},${y}h${w}v${hgt - r}a${r},${r} 0 0 1 ${-r},${r}h${-(w - 2 * r)}a${r},${r} 0 0 1 ${-r},${-r}Z`;
  }
  return `M${x},${y + r}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${hgt - r}h${-w}Z`;
}

function drawCartesian(container, model, width, animate) {
  const { categories, series, stacked, type } = model;
  const tip = tooltipBox();

  // y domain over the values (stack sums for stacked charts).
  let min = 0;
  let max = 0;
  categories.forEach((_, i) => {
    if (stacked) {
      let pos = 0;
      let neg = 0;
      for (const s of series) {
        const v = s.values[i] ?? 0;
        if (v >= 0) pos += v;
        else neg += v;
      }
      max = Math.max(max, pos);
      min = Math.min(min, neg);
    } else {
      for (const s of series) {
        const v = s.values[i];
        if (v === null) continue;
        max = Math.max(max, v);
        min = Math.min(min, v);
      }
    }
  });
  const ticks = niceTicks(min, max);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const yTitle = toAxisLabel(model.yKey);
  const xTitle = toAxisLabel(model.x);
  const widestY = Math.max(...ticks.map((t) => textWidth(formatCompact(t, model.yKey))));
  const left = Math.ceil(widestY + TICK_MARGIN + (yTitle ? TITLE_BAND : 0));
  const right = 8;
  const plotW = Math.max(40, width - left - right);
  const band = plotW / Math.max(categories.length, 1);
  const labels = categories.map((c) => String(c));
  const longestX = Math.max(...labels.map((l) => Math.min(l.length, 14)));
  const angled = longestX * CHAR_PX > band * 0.9 && longestX > 4;
  const slot = angled ? TICK_FONT_PX * 1.6 : longestX * CHAR_PX + 10;
  const every = Math.max(1, Math.ceil(slot / band));
  const xAxisH = angled
    ? Math.ceil(TICK_MARGIN + longestX * CHAR_PX * Math.sin(0.61) + TICK_FONT_PX + (xTitle ? TITLE_BAND : 4))
    : TICK_MARGIN + TICK_FONT_PX + (xTitle ? TITLE_BAND : 4);
  const top = 8;
  const plotH = CHART_HEIGHT - top - xAxisH;
  const y = (v) => top + plotH - ((v - yMin) / (yMax - yMin || 1)) * plotH;
  const cx = (i) => left + band * i + band / 2;

  const svg = h("svg:svg", {
    width,
    height: CHART_HEIGHT,
    viewBox: `0 0 ${width} ${CHART_HEIGHT}`,
    "aria-hidden": "true",
  });

  for (const t of ticks) {
    svg.append(
      h("svg:line", {
        class: t === 0 && yMin < 0 ? "zero" : "grid",
        x1: left,
        x2: left + plotW,
        y1: y(t),
        y2: y(t),
      }),
      h(
        "svg:text",
        { x: left - TICK_MARGIN, y: y(t), "text-anchor": "end", "dominant-baseline": "middle" },
        formatCompact(t, model.yKey)
      )
    );
  }
  if (yTitle) {
    svg.append(
      h(
        "svg:text",
        {
          class: "axis-title",
          transform: `translate(${10},${top + plotH / 2}) rotate(-90)`,
          "text-anchor": "middle",
          "dominant-baseline": "middle",
        },
        yTitle
      )
    );
  }

  // Hover bands under the marks.
  const bands = categories.map((_, i) =>
    h("svg:rect", { class: "band", x: left + band * i, y: top, width: band, height: plotH })
  );
  svg.append(...bands);

  labels.forEach((label, i) => {
    if (i % every !== 0) return;
    const text = label.length > 14 ? `${label.slice(0, 12)}…` : label;
    const ty = top + plotH + TICK_MARGIN + TICK_FONT_PX * 0.8;
    svg.append(
      h(
        "svg:text",
        angled
          ? { x: cx(i), y: ty, "text-anchor": "end", transform: `rotate(-35 ${cx(i)} ${ty})` }
          : { x: cx(i), y: ty, "text-anchor": "middle" },
        h("svg:title", {}, label),
        text
      )
    );
  });
  if (xTitle) {
    svg.append(
      h(
        "svg:text",
        { class: "axis-title", x: left + plotW / 2, y: CHART_HEIGHT - 3, "text-anchor": "middle" },
        xTitle
      )
    );
  }

  const isBar = type.includes("bar");
  const grow = animate ? " grow" : "";
  if (isBar) {
    const groups = stacked ? 1 : series.length;
    const inner = band * (categories.length > 40 ? 0.9 : 0.75);
    const barW = Math.max(1, inner / groups - (groups > 1 ? 2 : 0));
    categories.forEach((_, i) => {
      let pos = 0;
      let neg = 0;
      series.forEach((s, j) => {
        const v = s.values[i];
        if (v === null || v === 0) return;
        let y0;
        let y1;
        if (stacked) {
          y0 = v >= 0 ? pos : neg;
          y1 = y0 + v;
          if (v >= 0) pos = y1;
          else neg = y1;
        } else {
          y0 = 0;
          y1 = v;
        }
        const x0 = left + band * i + (band - inner) / 2 + (stacked ? 0 : j * (inner / groups));
        const yTop = y(Math.max(y0, y1));
        const hgt = Math.abs(y(y0) - y(y1));
        const color = model.divergent
          ? v >= 0
            ? model.divergent.positive
            : model.divergent.negative
          : s.color;
        const round = stacked ? 0 : 3;
        svg.append(
          h("svg:path", {
            class: `${grow}${v < 0 ? " down" : ""}`.trim() || undefined,
            d: barPath(x0, yTop, barW, hgt, round, v < 0),
            fill: color,
            style: animate ? { animationDelay: `${Math.min(i * 12, 300)}ms` } : undefined,
          })
        );
      });
    });
  } else {
    const fade = animate ? "fade" : undefined;
    let baseline = categories.map(() => 0);
    series.forEach((s) => {
      const points = [];
      s.values.forEach((v, i) => {
        if (v === null) return;
        const yv = stacked ? baseline[i] + v : v;
        points.push([cx(i), y(yv), i, stacked ? baseline[i] : 0]);
      });
      if (!points.length) return;
      const line = points.map((p, k) => `${k ? "L" : "M"}${p[0]},${p[1]}`).join("");
      if (type === "area") {
        const floor = points
          .slice()
          .reverse()
          .map((p) => `L${p[0]},${y(p[3])}`)
          .join("");
        svg.append(h("svg:path", { class: fade, d: `${line}${floor}Z`, fill: s.color, "fill-opacity": 0.2 }));
      }
      svg.append(
        h("svg:path", {
          class: fade,
          d: line,
          fill: "none",
          stroke: s.color,
          "stroke-width": 2,
          "stroke-dasharray": s.dash || undefined,
          "stroke-linejoin": "round",
        })
      );
      if (type !== "area" && categories.length <= MAX_LINE_DOTS) {
        for (const p of points) {
          svg.append(h("svg:circle", { class: fade, cx: p[0], cy: p[1], r: 2.5, fill: s.color }));
        }
      }
      if (stacked) {
        baseline = baseline.map((b, i) => b + (s.values[i] ?? 0));
      }
    });
  }

  const legend =
    series.length > 1
      ? h(
          "ul",
          { class: "legend" },
          series.map((s) =>
            h("li", {}, h("span", { class: "swatch", style: { background: s.color } }), s.label)
          )
        )
      : null;

  let active = -1;
  const setActive = (i, event) => {
    if (active >= 0) bands[active].classList.remove("active");
    active = i;
    if (i < 0) {
      tip.hidden = true;
      return;
    }
    bands[i].classList.add("active");
    const entries = series
      .filter((s) => s.values[i] !== null)
      .map((s) => ({
        label: s.label,
        color: model.divergent
          ? s.values[i] >= 0
            ? model.divergent.positive
            : model.divergent.negative
          : s.color,
        value: s.values[i],
      }));
    tip.replaceChildren(...tooltipRows(labels[i], entries, model.yKey));
    placeTooltip(tip, container, event.clientX, event.clientY);
  };
  svg.addEventListener("pointermove", (event) => {
    const box = svg.getBoundingClientRect();
    const px = event.clientX - box.left;
    const i = Math.floor((px - left) / band);
    if (i >= 0 && i < categories.length) setActive(i, event);
    else setActive(-1);
  });
  svg.addEventListener("pointerleave", () => setActive(-1));

  return [legend, svg, tip];
}

function arcPath(cx, cy, r0, r1, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (r, a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  if (a1 - a0 >= Math.PI * 2 - 1e-6) a1 = a0 + Math.PI * 2 - 1e-4;
  const [x0, y0] = p(r1, a0);
  const [x1, y1] = p(r1, a1);
  const [x2, y2] = p(r0, a1);
  const [x3, y3] = p(r0, a0);
  return `M${x0},${y0}A${r1},${r1} 0 ${large} 1 ${x1},${y1}L${x2},${y2}A${r0},${r0} 0 ${large} 0 ${x3},${y3}Z`;
}

function drawPie(container, spec, width, animate) {
  const rows = spec.chart_data || [];
  const x = spec.x_axis || columnsOf(rows)[0];
  const yKey = spec.y_axis || columnsOf(rows).find((k) => k !== x && isNumeric(rows[0]?.[k]));
  const slices = [];
  rows.forEach((row) => {
    const value = Number(row[yKey]);
    if (!Number.isFinite(value) || value <= 0) return;
    const label = String(row[x]);
    const existing = slices.find((s) => s.label === label);
    if (existing) {
      existing.value += value;
      return;
    }
    slices.push({
      label,
      value,
      color:
        spec.color_map?.[row[`${x}_slug`]] ||
        spec.color_map?.[label] ||
        PALETTE[slices.length % PALETTE.length],
    });
  });
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const size = 190;
  const r1 = size / 2 - 4;
  const r0 = r1 * 0.58;
  const c = size / 2;
  const tip = tooltipBox();
  const svg = h("svg:svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}`, "aria-hidden": "true" });
  const items = [];
  let angle = 0;
  const paths = slices.map((s) => {
    const a0 = angle;
    angle += (s.value / total) * Math.PI * 2;
    const path = h("svg:path", {
      class: `slice${animate ? " fade" : ""}`,
      d: arcPath(c, c, r0, r1, a0, angle),
      fill: s.color,
    });
    svg.append(path);
    return path;
  });
  svg.append(
    h("svg:text", { class: "total", x: c, y: c - 4, "text-anchor": "middle", "dominant-baseline": "central" }, formatCompact(total, yKey)),
    h("svg:text", { class: "total-label", x: c, y: c + 13, "text-anchor": "middle" }, unitOf(yKey) ? `total ${unitOf(yKey)}` : "total")
  );

  const legend = h(
    "ul",
    { class: "legend" },
    slices.map((s, i) => {
      const item = h(
        "li",
        {},
        h("span", { class: "swatch", style: { background: s.color } }),
        h("span", { class: "label", title: s.label }, s.label),
        h("span", { class: "num" }, formatShare(s.value, total))
      );
      items.push(item);
      item.addEventListener("pointerenter", (event) => setActive(i, event));
      item.addEventListener("pointerleave", () => setActive(-1));
      return item;
    })
  );

  const wrapper = h("div", { class: `pie${width < 420 ? " stacked" : ""}` }, svg, legend);
  const setActive = (i, event) => {
    paths.forEach((p, k) => p.classList.toggle("active", k === i));
    items.forEach((p, k) => p.classList.toggle("active", k === i));
    container.classList.toggle("hovering", i >= 0);
    if (i < 0) {
      tip.hidden = true;
      return;
    }
    const s = slices[i];
    tip.replaceChildren(
      ...tooltipRows(s.label, [
        { label: `${formatShare(s.value, total)} of total`, color: s.color, value: s.value },
      ], yKey)
    );
    placeTooltip(tip, container, event.clientX, event.clientY);
  };
  paths.forEach((p, i) => {
    p.addEventListener("pointermove", (event) => setActive(i, event));
    p.addEventListener("pointerleave", () => setActive(-1));
  });
  return [wrapper, tip];
}

function drawScatter(container, spec, width, animate) {
  const rows = (spec.chart_data || []).filter(
    (row) => isNumeric(row[spec.x_axis]) && isNumeric(row[spec.y_axis])
  );
  const xs = rows.map((row) => Number(row[spec.x_axis]));
  const ys = rows.map((row) => Number(row[spec.y_axis]));
  const xt = niceTicks(Math.min(0, ...xs), Math.max(...xs));
  const yt = niceTicks(Math.min(0, ...ys), Math.max(...ys));
  const left = 56;
  const top = 8;
  const plotW = width - left - 12;
  const plotH = CHART_HEIGHT - top - 40;
  const sx = (v) => left + ((v - xt[0]) / (xt[xt.length - 1] - xt[0])) * plotW;
  const sy = (v) => top + plotH - ((v - yt[0]) / (yt[yt.length - 1] - yt[0])) * plotH;
  const tip = tooltipBox();
  const color = spec.series_color || PALETTE[0];
  const svg = h("svg:svg", { width, height: CHART_HEIGHT, "aria-hidden": "true" });
  for (const t of yt) {
    svg.append(
      h("svg:line", { class: "grid", x1: left, x2: left + plotW, y1: sy(t), y2: sy(t) }),
      h("svg:text", { x: left - 6, y: sy(t), "text-anchor": "end", "dominant-baseline": "middle" }, formatCompact(t, spec.y_axis))
    );
  }
  for (const t of xt) {
    svg.append(h("svg:text", { x: sx(t), y: top + plotH + 16, "text-anchor": "middle" }, formatCompact(t, spec.x_axis)));
  }
  svg.append(
    h("svg:text", { class: "axis-title", x: left + plotW / 2, y: CHART_HEIGHT - 3, "text-anchor": "middle" }, toAxisLabel(spec.x_axis))
  );
  rows.forEach((row, i) => {
    const dot = h("svg:circle", { class: animate ? "fade" : undefined, cx: sx(xs[i]), cy: sy(ys[i]), r: 4, fill: color, "fill-opacity": 0.8 });
    dot.addEventListener("pointermove", (event) => {
      tip.replaceChildren(
        ...tooltipRows(String(row.name ?? ""), [
          { label: toAxisLabel(spec.x_axis), color, value: xs[i] },
          { label: toAxisLabel(spec.y_axis), color, value: ys[i] },
        ])
      );
      placeTooltip(tip, container, event.clientX, event.clientY);
    });
    dot.addEventListener("pointerleave", () => (tip.hidden = true));
    svg.append(dot);
  });
  return [svg, tip];
}

/** A chart element that redraws itself when its width changes. */
function chartView(spec) {
  const type = spec.chart_type;
  const rows = spec.chart_data || [];
  const label = `${type} chart: ${spec.title || ""}. ${
    type === "pie" ? `${rows.length} slices` : `${rows.length} data points`
  }.`;
  const container = h("div", { class: "chart", role: "img", "aria-label": label, tabindex: 0 });
  let lastWidth = 0;
  let animate = true;
  const draw = () => {
    const width = Math.floor(container.clientWidth);
    if (!width || width === lastWidth) return;
    lastWidth = width;
    let parts;
    if (type === "pie") parts = drawPie(container, spec, width, animate);
    else if (type === "scatter") parts = drawScatter(container, spec, width, animate);
    else parts = drawCartesian(container, cartesianModel(spec), width, animate);
    container.replaceChildren(...parts.filter(Boolean));
    animate = false;
  };
  new ResizeObserver(() => requestAnimationFrame(draw)).observe(container);
  return container;
}

const CHART_TYPES = new Set([
  "bar",
  "stacked-bar",
  "grouped-bar",
  "stacked-bar-with-line",
  "line",
  "area",
  "pie",
  "scatter",
]);

/** Chart / Table toggle over a chart, as WidgetMessage has. */
function chartWithTable(spec, { tableRows } = {}) {
  const rows = tableRows || spec.chart_data || [];
  if (!CHART_TYPES.has(spec.chart_type)) {
    return dataTable(rows, { caption: spec.title });
  }
  const body = h("div", {});
  const chartButton = h("button", { class: "btn", type: "button", "aria-pressed": "true" }, icon("chartBar", 14), "Chart");
  const tableButton = h("button", { class: "btn", type: "button", "aria-pressed": "false" }, icon("table", 14), "Table");
  let chart = null;
  let table = null;
  const show = (asTable) => {
    chartButton.setAttribute("aria-pressed", String(!asTable));
    tableButton.setAttribute("aria-pressed", String(asTable));
    if (asTable) {
      table = table || dataTable(rows, { caption: spec.title });
      body.replaceChildren(table);
    } else {
      chart = chart || chartView(spec);
      body.replaceChildren(chart);
    }
  };
  chartButton.addEventListener("click", () => show(false));
  tableButton.addEventListener("click", () => show(true));
  show(false);
  return h(
    "div",
    { class: "stack sm" },
    h("div", { class: "toolbar" }, h("div", { class: "segmented", role: "group", "aria-label": "Visualization format" }, chartButton, tableButton)),
    body
  );
}
