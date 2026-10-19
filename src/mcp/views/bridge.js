// The app side of the MCP Apps protocol (io.modelcontextprotocol/ui): JSON-RPC
// over postMessage with the host that draws this view in an iframe. The host
// sends the tool's arguments and result; the view sends its size, and asks the
// host to open links and to post messages to the chat.
const Bridge = (() => {
  const PROTOCOL_VERSION = "2026-01-26";
  const pending = new Map();
  const handlers = {};
  let nextId = 1;
  let hostContext = {};

  function post(message) {
    window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  }

  function request(method, params, timeoutMs = 10000) {
    const id = nextId++;
    post({ id, method, params });
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      setTimeout(() => {
        if (pending.delete(id)) reject(new Error(`${method} timed out`));
      }, timeoutMs);
    });
  }

  function notify(method, params) {
    post({ method, params });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (message.method === undefined && message.id !== undefined) {
      const waiter = pending.get(message.id);
      if (!waiter) return;
      pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message));
      else waiter.resolve(message.result);
      return;
    }
    const handler = handlers[message.method];
    if (handler) handler(message.params || {});
    // Host requests (resource teardown) expect an answer.
    if (message.id !== undefined) post({ id: message.id, result: {} });
  });

  function applyContext(context) {
    hostContext = { ...hostContext, ...context };
    const theme =
      hostContext.theme ||
      (window.matchMedia?.("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light");
    document.documentElement.dataset.theme = theme;
  }

  function watchSize() {
    let last = "";
    const report = () => {
      const rect = document.body.getBoundingClientRect();
      const size = {
        width: Math.ceil(rect.width),
        height: Math.ceil(rect.height),
      };
      const key = `${size.width}x${size.height}`;
      if (key === last) return;
      last = key;
      notify("ui/notifications/size-changed", size);
    };
    new ResizeObserver(report).observe(document.body);
    report();
  }

  /**
   * Connect to the host. `onResult` gets the CallToolResult (content,
   * structuredContent, isError); `onInput` the tool's arguments, which
   * arrive first, while the tool runs.
   */
  async function start({ onInput, onResult, onCancel }) {
    handlers["ui/notifications/tool-input"] = (params) =>
      onInput?.(params.arguments || {});
    handlers["ui/notifications/tool-result"] = (params) => onResult(params);
    handlers["ui/notifications/tool-cancelled"] = (params) =>
      onCancel?.(params.reason);
    handlers["ui/notifications/host-context-changed"] = applyContext;
    applyContext({});
    try {
      const result = await request("ui/initialize", {
        protocolVersion: PROTOCOL_VERSION,
        appInfo: { name: "gnw-views", version: "1.0.0" },
        appCapabilities: {},
      });
      applyContext(result?.hostContext || {});
    } catch (error) {
      console.warn("MCP Apps host did not answer ui/initialize", error);
    }
    notify("ui/notifications/initialized", {});
    watchSize();
  }

  /** Open a link through the host; the sandbox may block window.open. */
  async function openLink(url) {
    try {
      await request("ui/open-link", { url });
    } catch {
      window.open(url, "_blank", "noopener");
    }
  }

  /** Post a message to the chat as the user. Resolves false on failure. */
  async function sendMessage(text) {
    try {
      const result = await request("ui/message", {
        role: "user",
        content: [{ type: "text", text }],
      });
      return !result?.isError;
    } catch {
      return false;
    }
  }

  /** Call a tool on this server through the host. */
  function callTool(name, args) {
    return request("tools/call", { name, arguments: args }, 60000);
  }

  return {
    start,
    openLink,
    sendMessage,
    callTool,
    context: () => hostContext,
  };
})();
