// Reproduce: what a pull was and how to run it again. pull_data and
// curated_charts return a standalone pull.py, the request it sends and the
// pull's provenance; this panel shows them with a copy button, so the user
// can repeat the numbers outside the chat.

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

/** Source with line numbers and highlighting, in the .code box. */
function codeBlock(source) {
  return h("div", { class: "code", tabindex: 0 }, h("pre", {}, highlight(source || "")));
}

// The keys of a result that are data or views of it, not its provenance.
const NOT_PROVENANCE = new Set(["rows", "charts", "script", "row_count", "rows_truncated", "curated", "withheld", "request"]);

function provenanceOf(data) {
  return Object.fromEntries(Object.entries(data).filter(([key]) => !NOT_PROVENANCE.has(key)));
}

/** Copy `text`; when the sandbox blocks the clipboard, select `target` so
 * the user can copy it with the keyboard. */
function copyButton(getText, getTarget) {
  const label = h("span", {}, "Copy");
  const button = h("button", { class: "btn", type: "button" }, icon("copy", 14), label);
  const say = (text) => {
    label.textContent = text;
    setTimeout(() => (label.textContent = "Copy"), 2500);
  };
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(getText());
      say("Copied");
    } catch {
      const target = getTarget();
      const range = document.createRange();
      range.selectNodeContents(target);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      target.focus?.();
      say("Selected · copy with your keyboard");
    }
  });
  return button;
}

/** The Reproduce panel, closed until opened; null when there is no script. */
function reproducePanel(data) {
  if (!data.script) return null;
  const folder = `gnw/pulls/${data.result_id || "latest"}`;
  const tabs = [
    ["pull.py", () => data.script],
    ["Request", () => JSON.stringify(data.request, null, 2)],
    ["Provenance", () => JSON.stringify(provenanceOf(data), null, 2)],
  ];
  const body = h("div", {});
  let current = tabs[0];
  const buttons = tabs.map((tab) => {
    const button = h("button", { class: "btn", type: "button", "aria-pressed": "false" }, tab[0]);
    button.addEventListener("click", () => show(tab));
    return button;
  });
  const show = (tab) => {
    current = tab;
    buttons.forEach((button, i) => button.setAttribute("aria-pressed", String(tabs[i] === tab)));
    body.replaceChildren(codeBlock(tab[1]()));
  };
  show(tabs[0]);
  return h(
    "details",
    { class: "panel reproduce" },
    h(
      "summary",
      { class: "panel-header" },
      icon("code", 16),
      h("h2", {}, "Reproduce this pull"),
      h("span", { class: "spacer" }),
      h("span", { class: "eyebrow" }, "pull.py · request · provenance")
    ),
    h(
      "div",
      { class: "panel-body" },
      h(
        "div",
        { class: "muted" },
        "Save the script as pull.py and run ",
        h("code", { class: "mono" }, "python pull.py"),
        `. It sends the same request to the GNW analytics API and writes the rows, the request and this provenance to ${folder}/. Python 3.9 or later, no packages.`
      ),
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "segmented", role: "group", "aria-label": "Reproduce" }, buttons),
        h("span", { class: "spacer" }),
        copyButton(
          () => current[1](),
          () => body.querySelector("pre")
        )
      ),
      body
    )
  );
}
