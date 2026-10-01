(() => {
  let conversationId = "",
    controller,
    sending = false,
    poll,
    currentDraft,
    lastLinked,
    lastEventId = 0;
  const box = $("chat-messages");
  const welcome = box.firstElementChild.cloneNode(true);
  const scrollArea = $("chat-scroll");
  const status = (text) => {
    $("chat-status").textContent = text;
  };
  function bindSuggestions() {
    box.querySelectorAll("[data-prompt]").forEach((button) => {
      button.onclick = () => {
        $("chat-input").value = button.dataset.prompt;
        $("chat-input").focus();
      };
    });
  }
  function bubble(role, text) {
    const node = element("div", undefined, "chat-message " + role);
    node.append(
      element("strong", role === "user" ? "你" : "Nori"),
      element("div", role === "assistant" ? undefined : text, "chat-content"),
    );
    if (role === "assistant") window.financeRenderMarkdown(node.lastChild, text);
    box.append(node);
    scrollArea.scrollTop = scrollArea.scrollHeight;
    return node.lastChild;
  }
  function renderEvent(event) {
    if (event.type === "user" || event.type === "assistant")
      bubble(event.type, event.text);
    else if (event.type === "tool_start")
      box.append(element("div", "正在调用工具 · " + event.name, "chat-tool"));
    else if (event.type === "tool_end")
      box.append(
        element(
          "div",
          (event.is_error ? "工具未完成 · " : "工具完成 · ") + event.name,
          "chat-tool",
        ),
      );
    else if (event.type === "error")
      box.append(element("p", event.text, "danger"));
  }
  function reset() {
    controller?.abort();
    clearInterval(poll);
    conversationId = "";
    currentDraft = undefined;
    lastLinked = undefined;
    box.replaceChildren(welcome.cloneNode(true));
    bindSuggestions();
    $("conversation-list").replaceChildren(
      element("p", "连接工作区后显示对话"),
    );
    $("chat-linked-tasks").replaceChildren();
    $("chat-agent-tasks").replaceChildren();
    lastEventId = 0;
    $("conversation-select").replaceChildren(element("option", "开始新的对话"));
    status("等待连接");
  }
  async function list(resume = false) {
    const version = sessionVersion;
    const conversations = await api("/conversations");
    if (version !== sessionVersion) return;
    if (resume && !conversationId && conversations.length)
      conversationId = conversations[0].id;
    const select = $("conversation-select");
    select.replaceChildren();
    const blank = element("option", "开始新的对话");
    blank.value = "";
    select.append(blank);
    for (const c of conversations) {
      const o = element("option", c.title);
      o.value = c.id;
      select.append(o);
    }
    select.value = conversationId;
    const history = $("conversation-list");
    history.replaceChildren();
    if (!conversations.length)
      history.append(element("p", "还没有对话，从一个问题开始"));
    for (const c of conversations) {
      const button = element(
        "button",
        c.title,
        c.id === conversationId ? "active" : "",
      );
      button.type = "button";
      button.onclick = () => {
        select.value = c.id;
        select.dispatchEvent(new Event("change"));
      };
      history.append(button);
    }
    window.dispatchEvent(new Event("finance-conversation"));
  }
  let creatingConversation;
  window.financeEnsureConversation = async (title = "新的财务对话") => {
    if (conversationId) return conversationId;
    if (creatingConversation) return creatingConversation;
    const version = sessionVersion;
    creatingConversation = (async () => {
      const c = await api("/conversations", "POST", {
        title: title.slice(0, 120),
      });
      if (version !== sessionVersion) throw new Error("工作区连接已变更");
      conversationId = c.id;
      await list();
      return c.id;
    })();
    try {
      return await creatingConversation;
    } finally {
      creatingConversation = undefined;
    }
  };
  function renderTasks(tasks) {
    const serialized = JSON.stringify(tasks);
    if (serialized === lastLinked) return;
    lastLinked = serialized;
    $("chat-linked-tasks").replaceChildren();
    for (const task of tasks) {
      const card = element("div", undefined, "card");
      card.append(element("strong", task.name + " · " + state[task.status]));
      if (task.result?.equity)
        card.append(
          element(
            "p",
            "资金流调整后收益 " +
              task.result.equity.profit +
              " " +
              task.result.currency,
          ),
        );
      if (task.result) {
        const d = element("details");
        d.append(
          element("summary", "查看任务结果"),
          element("pre", JSON.stringify(task.result, null, 2)),
        );
        card.append(d);
      }
      $("chat-linked-tasks").append(card);
    }
  }
  async function load(full = true) {
    if (!conversationId || sending) return;
    const version = sessionVersion,
      id = conversationId;
    const c = await api("/conversations/" + id);
    if (version !== sessionVersion || id !== conversationId) return;
    if (full) {
      box.replaceChildren();
      lastEventId = 0;
      if (!c.events.length) {
        box.append(welcome.cloneNode(true));
        bindSuggestions();
      }
    }
    for (const e of c.events) {
      if (full || e.id > lastEventId) renderEvent({ type: e.type, ...e.payload });
      lastEventId = Math.max(lastEventId, e.id);
    }
    renderTasks(c.tasks);
    window.financeRenderAgentTasks($("chat-agent-tasks"), c.agent_tasks || []);
    if (full)
      status(c.running ? "该对话正在回复，稍后刷新查看" : "可以发送消息");
  }
  window.addEventListener("finance-agent-tasks-updated", () => load(false).catch(() => {}));
  window.addEventListener("finance-session-reset", reset);
  window.addEventListener("finance-session-ready", async () => {
    const version = sessionVersion;
    try {
      window.financeConversationReady = (async () => {
        await list(true);
        if (conversationId) await load();
      })();
      await window.financeConversationReady;
      if (version !== sessionVersion) return;
      status("可以发送消息");
      poll = setInterval(() => load(false).catch(() => {}), 5000);
    } catch (e) {
      if (version === sessionVersion) status(e.message);
    }
  });
  $("new-chat").onclick = () => {
    if (sending) return;
    conversationId = "";
    currentDraft = undefined;
    lastLinked = undefined;
    $("conversation-select").value = "";
    box.replaceChildren(welcome.cloneNode(true));
    bindSuggestions();
    window.dispatchEvent(new Event("finance-conversation"));
    document
      .querySelectorAll("#conversation-list button")
      .forEach((button) => button.classList.remove("active"));
    $("chat-linked-tasks").replaceChildren();
    $("chat-agent-tasks").replaceChildren();
    lastEventId = 0;
    status("新的对话");
  };
  $("conversation-select").onchange = async (e) => {
    if (sending) {
      e.target.value = conversationId;
      return;
    }
    lastLinked = undefined;
    conversationId = e.target.value;
    currentDraft = undefined;
    if (!conversationId) return $("new-chat").click();
    try {
      await load();
      await list();
    } catch (e) {
      status(e.message);
    }
  };
  $("chat-stop").onclick = () => controller?.abort();
  $("chat-form").onsubmit = async (e) => {
    e.preventDefault();
    if (sending) return;
    const version = sessionVersion;
    sending = true;
    $("chat-send").disabled = true;
    $("chat-stop").disabled = false;
    controller = new AbortController();
    let draftBubble, draftText = "", errorText, waiting, waitingTimer;
    const started = Date.now();
    const showWaiting = (text) => {
      if (!waiting) return;
      waiting.querySelector(".waiting-label").textContent = text;
      waiting.hidden = false;
      box.append(waiting);
      scrollArea.scrollTop = scrollArea.scrollHeight;
    };
    try {
      if (!workspaceReady) throw new Error("工作区正在连接，请稍后发送");
      const text = $("chat-input").value.trim();
      if (!text) throw new Error("请输入问题");
      const snapshot = undefined;
      if (box.querySelector(".chat-welcome")) box.replaceChildren();
      bubble("user", text);
      waiting = element("div", undefined, "chat-waiting");
      waiting.setAttribute("role", "status");
      waiting.append(element("span", undefined, "waiting-spinner"));
      const waitingContent = element("div");
      waitingContent.append(
        element("div", "助手正在准备回复…", "waiting-label"),
        element("small", "正在整理问题，请稍候。", "waiting-detail"),
      );
      waiting.append(waitingContent);
      showWaiting("助手正在准备回复…");
      waitingTimer = setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        waiting.querySelector(".waiting-detail").textContent =
          seconds >= 15
            ? "已等待 " + seconds + " 秒，仍在处理，复杂问题可能需要一点时间。"
            : "已等待 " + seconds + " 秒，请稍候。";
      }, 1000);
      status("助手正在准备回复…");
      await window.financeEnsureConversation(text);
      if (version !== sessionVersion) return;
      const allowMonitor = false;
      const fingerprint = JSON.stringify([
        conversationId,
        text,
        snapshot,
        allowMonitor,
      ]);
      if (currentDraft?.fingerprint !== fingerprint)
        currentDraft = { fingerprint, id: crypto.randomUUID() };
      status("助手正在处理…");
      const r = await fetch(
        "/api/conversations/" + conversationId + "/messages",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            request_id: currentDraft.id,
            message: text,
            snapshot,
            allow_monitor_changes: allowMonitor,
          }),
          signal: controller.signal,
        },
      );
      if (version !== sessionVersion) return;
      if (!r.ok) {
        const error = await r.json();
        throw new Error(
          typeof error.detail === "string"
            ? error.detail
            : JSON.stringify(error.detail),
        );
      }
      $("chat-input").value = "";
      currentDraft = undefined;
      const reader = r.body.getReader(),
        decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (version !== sessionVersion) return;
        buffer += decoder.decode(value, { stream: !done });
        const lines = buffer.split("\n");
        buffer = lines.pop();
        for (const line of lines) {
          if (!line) continue;
          const event = JSON.parse(line);
          if (event.type === "text_delta") {
            waiting.hidden = true;
            draftBubble ??= bubble("assistant", "");
            draftText += event.text;
            window.financeRenderMarkdown(draftBubble, draftText);
            scrollArea.scrollTop = scrollArea.scrollHeight;
          } else if (event.type === "assistant") {
            waiting.hidden = true;
            if (draftBubble) {
              window.financeRenderMarkdown(draftBubble, event.text);
              draftBubble = undefined;
              draftText = "";
            } else renderEvent(event);
          } else if (event.type === "run_complete")
            status(event.limited ? "本轮达到工具预算，请继续追问" : "回复完成");
          else {
            renderEvent(event);
            if (event.type === "run_start") showWaiting("助手正在思考…");
            if (event.type === "tool_start") {
              const label = {
                desktop_action: "正在查看和操作 Linux 桌面…",
                terminal_exec: "正在检查工作区…",
                exchange_query: "正在查询交易所数据…",
                analyze_snapshot: "正在计算财务数据…",
              }[event.name] ?? "助手正在使用工具处理问题…";
              showWaiting(label);
            }
            if (event.type === "tool_end") {
              showWaiting("正在整理工具结果…");
              if (["desktop_action", "terminal_exec"].includes(event.name) || event.name?.startsWith("mcp_chrome_"))
                window.dispatchEvent(new Event("finance-desktop-used"));
            }
          }
        }
        if (done) break;
      }
    } catch (error) {
      if (version === sessionVersion) {
        errorText =
          error.name === "AbortError"
            ? "已停止回复。已提交的任务仍可查看。"
            : error.message;
        status(errorText);
      }
    } finally {
      clearInterval(waitingTimer);
      waiting?.remove();
      sending = false;
      $("chat-send").disabled = false;
      $("chat-stop").disabled = true;
      if (version === sessionVersion && conversationId) {
        await load().catch(() => {});
        await refresh();
        if (errorText) status(errorText);
      }
    }
  };
})();
