import type { StreamFn } from "@earendil-works/pi-agent-core";
import type { Model, Api } from "@earendil-works/pi-ai";
import { createInterface } from "node:readline";
import { financeTool, runAgent, type Start, type Emit } from "./runtime.js";
import { connectMcp, type McpConfig } from "./mcp.js";

export function serve(override?: { model: Model<Api>; stream: StreamFn }) {
  const lines = createInterface({ input: process.stdin });
  const pending = new Map<
    string,
    { resolve: (value: unknown) => void; reject: (error: Error) => void }
  >();
  const emit: Emit = (event) =>
    process.stdout.write(JSON.stringify(event) + "\n");
  let started = false;
  lines.on("line", (line) => {
    try {
      const message = JSON.parse(line);
      if (!started) {
        started = true;
        void main(message).then(
          () => process.stdout.write("", () => process.exit(0)),
          () => {
            emit({ type: "error", code: "agent_unavailable" });
            process.stdout.write("", () => process.exit(1));
          },
        );
      } else if (message.type === "tool_result") {
        const waiter = pending.get(message.call_id);
        pending.delete(message.call_id);
        if (message.error) waiter?.reject(new Error(message.error));
        else waiter?.resolve(message.result);
      }
    } catch {
      emit({ type: "error", code: "invalid_runtime_message" });
      process.exit(1);
    }
  });
  lines.on("close", () => process.exit(0));
  async function main(start: Start & { mcp: McpConfig[] }) {
    const request = async (
      name: string,
      args: unknown,
      callId: string,
      gate = false,
    ) => {
      const result = new Promise((resolve, reject) =>
        pending.set(callId, { resolve, reject }),
      );
      emit({ type: "tool_request", name, args, call_id: callId, gate });
      return result;
    };
    const mcp = await connectMcp(start.mcp, emit, async (name, callId) => {
      await request(name, {}, "gate-" + callId, true);
    });
    try {
      const local = start.tools.map((def) =>
        financeTool(def, (name, args, callId) => request(name, args, callId)),
      );
      await runAgent(start, [...local, ...mcp.tools], emit, override);
    } finally {
      await mcp.close();
    }
  }
}
