import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { financeTool, type Emit } from "./runtime.js";
import type { AgentTool } from "@earendil-works/pi-agent-core";

export interface McpConfig {
  name: string;
  command: string;
  args?: string[];
  env_names?: string[];
  allowed_tools: string[];
  // Pinned schemas allow tools to be advertised without starting a desktop.
  lazy_tools?: { name: string; description?: string; inputSchema: Record<string, unknown> }[];
}
export async function connectMcp(
  configs: McpConfig[],
  emit: Emit,
  authorize?: (name: string, callId: string) => Promise<void>,
) {
  const clients: Client[] = [];
  const tools: AgentTool[] = [];
  const names = new Set<string>();
  try {
    for (const config of configs) {
      if (
        !/^[a-z][a-z0-9_]{0,30}$/.test(config.name) ||
        !config.command.startsWith("/") ||
        !config.allowed_tools.length
      )
        throw new Error("Invalid administrator MCP configuration");
      const env: Record<string, string> = {
        PATH: process.env.PATH ?? "/usr/bin:/bin",
      };
      for (const name of config.env_names ?? []) {
        if (!process.env[name]) throw new Error("MCP environment unavailable");
        env[name] = process.env[name]!;
      }
      let client: Client;
      let available: Awaited<ReturnType<Client["listTools"]>>;
      let connection: Promise<void> | undefined;
      const activate = () => connection ??= (async () => {
        client = new Client({ name: "finance-agent", version: "0.2.0" });
        clients.push(client);
        await client.connect(new StdioClientTransport({
          command: config.command, args: config.args, env, stderr: "ignore",
        }));
        available = await client.listTools({}, { timeout: 10_000 });
        for (const name of config.allowed_tools)
          if (!available.tools.some(t => t.name === name))
            throw new Error("Configured MCP tool unavailable");
      })();
      if (!config.lazy_tools) await activate();
      const definitions = config.lazy_tools ?? available!.tools;
      for (const name of config.allowed_tools) {
        const remote = definitions.find((t) => t.name === name);
        if (!remote || !/^[a-zA-Z][a-zA-Z0-9_]{0,50}$/.test(name))
          throw new Error("Configured MCP tool unavailable");
        const alias = `mcp_${config.name}_${name}`;
        if (alias.length > 64 || names.has(alias))
          throw new Error("MCP tool alias invalid");
        names.add(alias);
        tools.push(
          financeTool(
            {
              name: alias,
              description:
                `External evidence from administrator-configured MCP ${config.name}. ${remote.description ?? name}`.slice(
                  0,
                  2000,
                ),
              parameters: remote.inputSchema,
            },
            async (_, args, callId, signal) => {
              await authorize?.(alias, callId);
              await activate();
              const result = await client!.callTool(
                { name, arguments: args as Record<string, unknown> },
                undefined,
                { timeout: 20_000, signal },
              );
              if (JSON.stringify(result).length > 100_000)
                throw new Error("MCP result exceeds limit");
              if (result.isError) throw new Error("MCP tool failed");
              emit({
                type: "mcp_result",
                call_id: callId,
                name: alias,
                result,
              });
              return result;
            },
          ),
        );
      }
    }
    return {
      tools,
      close: async () => {
        await Promise.allSettled(clients.map((c) => c.close()));
      },
    };
  } catch {
    await Promise.allSettled(clients.map((c) => c.close()));
    throw new Error("MCP connection unavailable");
  }
}
