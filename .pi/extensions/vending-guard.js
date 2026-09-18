import { isToolCallEventType } from "@earendil-works/pi-coding-agent";

function initialState() {
  return {
    hasEnv: false,
    observed: false,
    initialized: false,
    pricedProducts: new Set(),
    purchasedProducts: new Set(),
  };
}

function parseBody(command) {
  const quoted = command.match(/-d\s+'([^']+)'/);
  const doubleQuoted = command.match(/-d\s+"([^"]+)"/);
  const raw = quoted?.[1] ?? doubleQuoted?.[1];
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

function parseRequest(command) {
  if (!command.includes("curl") || !command.includes("/env")) return null;
  const methodMatch = command.match(/\s-X\s+(POST|GET|DELETE)\b/);
  const method = methodMatch?.[1] ?? "GET";

  const envAction = command.match(/\/env\/\$?\{?ENV_ID\}?\/?([a-z_]+)?/i);
  if (envAction) {
    const action = envAction[1] ?? null;
    return {
      method,
      path: envAction[0],
      action,
      body: parseBody(command),
    };
  }

  const createMatch = command.match(/\/env(?:[\"'\s]|$)/);
  if (createMatch) {
    return {
      method,
      path: "/env",
      action: null,
      body: parseBody(command),
    };
  }
  return null;
}

function isErrorResult(output) {
  try {
    const parsed = JSON.parse(output);
    return typeof parsed.error === "object" && parsed.error !== null;
  } catch {
    return false;
  }
}

function extractEnvId(output) {
  try {
    const parsed = JSON.parse(output);
    return typeof parsed.env_id === "string" ? parsed.env_id : null;
  } catch {
    return null;
  }
}

function offerAccepted(output) {
  try {
    const parsed = JSON.parse(output);
    const result = parsed.result;
    return result?.outcome === "accepted";
  } catch {
    return false;
  }
}

function getOutputText(content) {
  if (!Array.isArray(content)) return "";
  const first = content[0];
  if (!first || first.type !== "text" || typeof first.text !== "string") return "";
  return first.text.trim();
}

export default function (pi) {
  let state = initialState();
  const callMap = new Map();

  pi.on("session_start", async () => {
    state = initialState();
    callMap.clear();
  });

  pi.on("tool_call", async (event) => {
    if (!isToolCallEventType("bash", event)) return;
    const request = parseRequest(event.input.command);
    if (!request) return;
    callMap.set(event.toolCallId, request);

    const action = request.action;
    const productId =
      typeof request.body.product_id === "string" ? request.body.product_id : undefined;

    if (request.path === "/env" && request.method === "POST") {
      return;
    }

    if (!state.hasEnv && action !== null) {
      return {
        block: true,
        reason: "Graph guard: create environment first with POST /env.",
      };
    }

    if (action === "observe") {
      if (state.observed) {
        return {
          block: true,
          reason: "Graph guard: observe is startup-only unless data is missing.",
        };
      }
      return;
    }

    if (action === "status" || request.method === "DELETE") {
      return;
    }

    if (!state.observed) {
      return {
        block: true,
        reason: "Graph guard: run observe once before operational actions.",
      };
    }

    if (action === "stock_items") {
      if (!productId || !state.pricedProducts.has(productId)) {
        return {
          block: true,
          reason: "Graph guard: stock_items requires set_price for that product first.",
        };
      }
      if (!state.purchasedProducts.has(productId)) {
        return {
          block: true,
          reason: "Graph guard: stock_items requires an accepted make_offer for that product.",
        };
      }
    }

    if (action === "end_day" && !state.initialized) {
      return {
        block: true,
        reason: "Graph guard: initialize at least one priced and stocked product before end_day.",
      };
    }
  });

  pi.on("tool_result", async (event) => {
    const request = callMap.get(event.toolCallId);
    if (!request) return;

    const output = getOutputText(event.content);
    if (!output || isErrorResult(output)) return;

    if (request.path === "/env" && request.method === "POST") {
      if (extractEnvId(output)) state.hasEnv = true;
      return;
    }

    const action = request.action;
    const productId =
      typeof request.body.product_id === "string" ? request.body.product_id : undefined;

    if (action === "observe") {
      state.observed = true;
      return;
    }

    if (action === "set_price" && productId) {
      state.pricedProducts.add(productId);
      return;
    }

    if (action === "make_offer" && productId && offerAccepted(output)) {
      state.purchasedProducts.add(productId);
      return;
    }

    if (action === "stock_items" && productId) {
      state.initialized = true;
    }
  });
}
