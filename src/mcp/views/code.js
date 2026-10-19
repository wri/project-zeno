// get_chart_code: the generator's source with line numbers and light
// Python highlighting (highlight, in reproduce.js).

function render(data) {
  return panel({
    iconName: "code",
    title: data.name || "Chart generator",
    headerExtra: data.code_url && linkButton("GitHub", data.code_url),
    children: [
      data.description && h("div", { class: "muted" }, data.description),
      h("div", { class: "eyebrow" }, data.path),
      h("div", { class: "code", tabindex: 0 }, h("pre", {}, highlight(data.source || ""))),
    ],
  });
}

mountView({
  pending: (args) => loading(`Reading the chart code of dataset ${args.dataset_id}…`),
  render,
});
