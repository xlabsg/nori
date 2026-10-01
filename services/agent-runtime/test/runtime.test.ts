import assert from "node:assert/strict";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createModels, type AssistantMessage } from "@earendil-works/pi-ai";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/utils/event-stream";
import { financeTool, runAgent, type ToolDefinition } from "../src/runtime.js";
import { connectMcp } from "../src/mcp.js";

const definition: ToolDefinition = {
  name: "analyze_snapshot",
  description: "Calculate fixture",
  parameters: { type: "object", properties: {}, additionalProperties: false },
};
const models = createModels();
models.setProvider(anthropicProvider());
const model = models.getModel("anthropic", "claude-sonnet-4-6")!;
const usage = {
  input: 0,
  output: 0,
  cacheRead: 0,
  cacheWrite: 0,
  totalTokens: 0,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
};

test("real Pi loop calls tool and follows its result before answering", async () => {
  let requests = 0,
    calls = 0;
  const events: Record<string, unknown>[] = [];
  const tool = financeTool(definition, async () => {
    calls++;
    return { profit: "500", currency: "USD" };
  });
  await runAgent(
    { prompt: "分析快照", messages: [], tools: [definition] },
    [tool],
    (e) => events.push(e),
    {
      model,
      stream: (_model, context) => {
        requests++;
        const stream = createAssistantMessageEventStream();
        const content: AssistantMessage["content"] =
          requests === 1
            ? [
                {
                  type: "toolCall",
                  id: "call-1",
                  name: definition.name,
                  arguments: {},
                },
              ]
            : [{ type: "text", text: "资金流调整后收益为 500 USD。" }];
        if (requests === 2) {
          const result = context.messages.find((m) => m.role === "toolResult");
          assert.ok(result && JSON.stringify(result).includes("500"));
        }
        const message: AssistantMessage = {
          role: "assistant",
          content,
          api: model.api,
          provider: model.provider,
          model: model.id,
          usage,
          stopReason: requests === 1 ? "toolUse" : "stop",
          timestamp: Date.now(),
        };
        stream.push({ type: "start", partial: message });
        if (requests === 2)
          stream.push({
            type: "text_delta",
            contentIndex: 0,
            delta: "资金流调整后收益为 500 USD。",
            partial: message,
          });
        stream.push({
          type: "done",
          reason: message.stopReason as "stop" | "toolUse",
          message,
        });
        stream.end(message);
        return stream;
      },
    },
  );
  assert.equal(requests, 2);
  assert.equal(calls, 1);
  assert.ok(events.some((e) => e.type === "tool_start"));
  assert.ok(events.some((e) => e.type === "text_delta"));
  assert.ok(events.some((e) => e.type === "complete"));
});

test("Pi budget prevents unbounded tool loops", async () => {
  let requests = 0;
  const events: Record<string, unknown>[] = [];
  await runAgent(
    { prompt: "loop", messages: [], tools: [definition] },
    [financeTool(definition, async () => ({ ok: true }))],
    (e) => events.push(e),
    {
      model,
      stream: () => {
        const stream = createAssistantMessageEventStream();
        const message: AssistantMessage = {
          role: "assistant",
          content: [
            {
              type: "toolCall",
              id: `call-${++requests}`,
              name: definition.name,
              arguments: {},
            },
          ],
          api: model.api,
          provider: model.provider,
          model: model.id,
          usage,
          stopReason: "toolUse",
          timestamp: Date.now(),
        };
        stream.push({ type: "done", reason: "toolUse", message });
        stream.end(message);
        return stream;
      },
    },
  );
  assert.equal(requests, 6);
  assert.ok(events.some((e) => e.type === "complete" && e.limited));
});

test("official MCP client discovers and invokes allowlisted stdio tool", async () => {
  const connection = await connectMcp(
    [
      {
        name: "demo",
        command: process.execPath,
        args: [
          fileURLToPath(
            new URL(
              "../../../examples/mcp/snapshot-server.mjs",
              import.meta.url,
            ),
          ),
        ],
        allowed_tools: ["get_demo_snapshot"],
      },
    ],
    () => {},
  );
  try {
    assert.deepEqual(
      connection.tools.map((t) => t.name),
      ["mcp_demo_get_demo_snapshot"],
    );
    const result = await connection.tools[0].execute("mcp-1", {});
    assert.ok(JSON.stringify(result).includes("synthetic MCP fixture"));
    assert.ok(JSON.stringify(result).includes("12500"));
  } finally {
    await connection.close();
  }
});

test("MCP configuration rejects arbitrary command and empty tool permissions", async () => {
  await assert.rejects(
    connectMcp(
      [{ name: "demo", command: "node", allowed_tools: ["x"] }],
      () => {},
    ),
  );
  await assert.rejects(
    connectMcp(
      [{ name: "demo", command: process.execPath, allowed_tools: [] }],
      () => {},
    ),
  );
});

test("MCP call is blocked when the shared authorization gate denies it", async () => {
  let gates = 0;
  const connection = await connectMcp(
    [
      {
        name: "demo",
        command: process.execPath,
        args: [
          fileURLToPath(
            new URL(
              "../../../examples/mcp/snapshot-server.mjs",
              import.meta.url,
            ),
          ),
        ],
        allowed_tools: ["get_demo_snapshot"],
      },
    ],
    () => {},
    async () => {
      gates++;
      throw new Error("Lease expired");
    },
  );
  try {
    await assert.rejects(
      connection.tools[0].execute("call-1", {}),
      /Lease expired/,
    );
    assert.equal(gates, 1);
  } finally {
    await connection.close();
  }
});

test("desktop screenshots become image blocks rather than base64 text", async () => {
  const tool = financeTool({ ...definition, name: "desktop_action" }, async () => ({
    action: "screenshot", width: 1280, height: 800,
    mime_type: "image/jpeg", screenshot_base64: "fixture-image-data",
  }));
  const result = await tool.execute("screen", {});
  assert.ok(result.content.some((block) => block.type === "image" && block.data === "fixture-image-data"));
  assert.ok(!JSON.stringify(result.details).includes("fixture-image-data"));
  assert.ok(result.content.filter((block) => block.type === "text").every((block) => !JSON.stringify(block).includes("fixture-image-data")));
});

test("lazy browser MCP advertises tools without spawning its container command", async () => {
  const connection = await connectMcp([{
    name: "chrome", command: "/nonexistent/desktop-command",
    allowed_tools: ["list_pages"],
    lazy_tools: [{name: "list_pages", inputSchema: {type: "object", properties: {}}}],
  }], () => {}, async () => {throw new Error("Lease expired");});
  try {
    assert.equal(connection.tools[0].name, "mcp_chrome_list_pages");
    await assert.rejects(connection.tools[0].execute("denied", {}), /Lease expired/);
  } finally {await connection.close();}
});
