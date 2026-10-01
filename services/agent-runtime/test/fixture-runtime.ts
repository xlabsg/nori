// Test-only provider: exercises real Pi orchestration without a paid model request.
import { createModels, type AssistantMessage } from "@earendil-works/pi-ai";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { createAssistantMessageEventStream } from "@earendil-works/pi-ai/utils/event-stream";
import { serve } from "../src/main.js";
const models = createModels();
models.setProvider(anthropicProvider());
const model = models.getModel("anthropic", "claude-sonnet-4-6")!;
let turn = 0;
serve({
  model,
  stream: () => {
    turn++;
    const stream = createAssistantMessageEventStream();
    const content: AssistantMessage["content"] =
      turn === 1
        ? [
            {
              type: "toolCall",
              id: "math-1",
              name: "analyze_snapshot",
              arguments: {},
            },
          ]
        : turn === 2
          ? [
              {
                type: "toolCall",
                id: "job-1",
                name: "create_analysis",
                arguments: { name: "快照分析" },
              },
            ]
          : [
              {
                type: "text",
                text: "模拟模型测试：工具计算的资金流调整后收益是 500 USD；分析任务已入队，完成后会收到提醒。",
              },
            ];
    const message: AssistantMessage = {
      role: "assistant",
      content,
      api: model.api,
      provider: model.provider,
      model: model.id,
      usage: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      },
      stopReason: turn < 3 ? "toolUse" : "stop",
      timestamp: Date.now(),
    };
    stream.push({ type: "start", partial: message });
    if (turn === 3)
      stream.push({
        type: "text_delta",
        contentIndex: 0,
        delta: (content[0] as { text: string }).text,
        partial: message,
      });
    stream.push({
      type: "done",
      reason: turn < 3 ? "toolUse" : "stop",
      message,
    });
    stream.end(message);
    return stream;
  },
});
