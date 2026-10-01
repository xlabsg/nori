import {writeFile} from 'node:fs/promises';
import {Client} from '../services/agent-runtime/node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js';
import {StdioClientTransport} from '../services/agent-runtime/node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js';
const client=new Client({name:'schema-export',version:'1'});
try {
 await client.connect(new StdioClientTransport({command:'npx',args:['-y','chrome-devtools-mcp@1.10.1','--browser-url=http://127.0.0.1:9222','--no-usage-statistics','--no-performance-crux'],stderr:'ignore'}));
 const {tools}=await client.listTools();
 const allowed=['list_pages','select_page','new_page','navigate_page','take_snapshot','click','fill','press_key','wait_for','evaluate_script','list_console_messages','list_network_requests'];
 const selected=allowed.map(name=>{const t=tools.find(t=>t.name===name);if(!t)throw Error(name);return {name:t.name,description:t.description,inputSchema:t.inputSchema};});
 await writeFile('infra/desktop/chrome-tools.json',JSON.stringify(selected,null,2)+'\n');
 console.log(selected.map(t=>t.name).join(', '));
}finally{await client.close();}process.exit(0);
