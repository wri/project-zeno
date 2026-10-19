// get_chart_code: the generator's source with line numbers and light
// Python highlighting.

const PY_TOKEN =
  /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(def|class)(\s+)([A-Za-z_]\w*)|\b(and|as|assert|async|await|break|continue|elif|else|except|finally|for|from|if|import|in|is|lambda|None|not|or|pass|raise|return|True|False|try|while|with|yield)\b/g;

/** Highlighted spans for a source, split into lines afterwards. */
function highlight(source) {
  const parts = [];
  let last = 0;
  for (const match of source.matchAll(PY_TOKEN)) {
    if (match.index > last) parts.push([null, source.slice(last, match.index)]);
    if (match[1]) parts.push(["com", match[1]]);
    else if (match[2]) parts.push(["str", match[2]]);
    else if (match[3]) parts.push(["kw", match[3]], [null, match[4]], ["def", match[5]]);
    else parts.push(["kw", match[6]]);
    last = match.index + match[0].length;
  }
  parts.push([null, source.slice(last)]);

  const lines = [[]];
  for (const [cls, text] of parts) {
    text.split("\n").forEach((piece, i) => {
      if (i > 0) lines.push([]);
      if (piece) lines[lines.length - 1].push(cls ? h("span", { class: cls }, piece) : piece);
    });
  }
  return lines.map((line) => h("span", { class: "ln" }, line.length ? line : " "));
}

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
