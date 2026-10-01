// Local read-only MCP example. Every value is synthetic; no network requests.
import { McpServer } from "../../services/agent-runtime/node_modules/@modelcontextprotocol/sdk/dist/esm/server/mcp.js";
import { StdioServerTransport } from "../../services/agent-runtime/node_modules/@modelcontextprotocol/sdk/dist/esm/server/stdio.js";
const server = new McpServer({name:"synthetic-finance-data",version:"1.0.0"});
server.registerTool("get_demo_snapshot", {description:"Return synthetic demo financial data, NOT live market prices."}, async () => ({content:[{type:"text",text:JSON.stringify({currency:"USD", observed_at:"2026-10-01T00:00:00Z", source:"synthetic MCP fixture", opening_equity:"10000", closing_equity:"12500", cash_flows:[{kind:"deposit",amount:"2000",external:true}]})}]}));
await server.connect(new StdioServerTransport());
