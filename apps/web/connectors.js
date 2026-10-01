(() => {
  const t = window.noriI18n?.t || ((text) => text);
  let poll;
  const renderedTasks = new WeakMap();
  const statusLabels = {connected: t("已连接"), disconnected: t("已断开"), needs_reconnect: t("需要重新连接")};
  const taskLabels = {enabled: t("已启用"), paused: t("已暂停"), completed: t("已完成"), cancelled: t("已取消"), needs_connection: t("需要连接账号")};
  const runLabels = {...state, retrying: t("重试中")};
  const errorLabels = {needs_reconnect: t("请重新连接 Google"), permission_denied: t("Google 拒绝访问，请检查 API 和账号权限"),
    gmail_api_disabled: t("请在 Google Cloud 启用 Gmail API"),
    calendar_api_disabled: t("请在 Google Cloud 启用 Google Calendar API"),
    insufficient_scopes: t("请重新连接并授权邮件和日历只读访问"),
    domain_policy_denied: t("请联系 Google Workspace 管理员开放访问"),
    rate_limited: t("请求频率受限，稍后重试"), sync_busy: t("正在同步，稍后重试"), sync_timeout: t("同步超时，稍后重试"),
    agent_unavailable: t("暂未生成结果，请稍后重试"), sync_backlog_limit: t("待同步内容较多，本次未完成"),
    analysis_input_limit: t("本次内容超过分析容量"), lease_expired: t("执行中断，将在后续任务中继续处理")};
  const stamp = value => value ? new Date(value * 1000).toLocaleString(window.noriI18n?.language) : "—";
  function button(text, handler) {
    const b = element("button", text, "secondary");
    b.type = "button";
    b.onclick = async () => {
      b.disabled = true;
      try {await handler(); await refreshConnections();}
      catch(e) {message(e.message, true);}
      finally {b.disabled = false;}
    };
    return b;
  }
  function scheduleLabel(s) {
    if (s.kind === "interval") return t("每 ") + s.interval_seconds / 60 + t(" 分钟");
    if (s.kind === "daily") return t("每天 ") + s.at + " · " + s.timezone;
    return new Date(s.run_at).toLocaleString(window.noriI18n?.language);
  }
  window.financeRenderAgentTasks = (container, tasks, emptyText = "") => {
    const serialized = JSON.stringify([tasks, emptyText]);
    if (renderedTasks.get(container) === serialized && (container.children.length || !tasks.length)) return;
    renderedTasks.set(container, serialized);
    container.replaceChildren();
    if (!tasks.length && emptyText) container.append(element("p", emptyText));
    for (const task of tasks) {
      const card = element("article", undefined, "card agent-task-card");
      card.append(element("strong", task.name + " · " + (taskLabels[task.status] || task.status)),
        element("p", scheduleLabel(task.schedule) + (task.mode === "calendar_reminder" ? t(" · 会议前 ") + task.reminder_minutes + t(" 分钟提醒") : "")),
        element("p", t("上次成功 ") + stamp(task.last_success_at) + t(" · 下次运行 ") + stamp(task.next_at)));
      const error = task.error_code || task.last_run?.error_code;
      if (task.last_run) card.append(element("p", t("最近执行 · ") + (runLabels[task.last_run.status] || task.last_run.status)));
      if (error) card.append(element("p", t("最近执行未完成：") + (errorLabels[error] || t("请查看执行记录后重试")), "danger"));
      if (!["completed", "cancelled"].includes(task.status)) card.append(button(task.status === "enabled" ? t("暂停") : t("恢复"), async () => {
        await api("/agent-tasks/" + task.id, "PATCH", {enabled: task.status !== "enabled"});
        window.dispatchEvent(new Event("finance-agent-tasks-updated"));
      }));
      if (task.status === "enabled") card.append(button(t("立即检查"), async () => {
        await api("/agent-tasks/" + task.id + "/run", "POST");
        window.dispatchEvent(new Event("finance-agent-tasks-updated"));
      }));
      if (!["completed", "cancelled"].includes(task.status)) card.append(button(t("取消任务"), async () => {
        await api("/agent-tasks/" + task.id + "/cancel", "POST");
        window.dispatchEvent(new Event("finance-agent-tasks-updated"));
      }));
      const history = element("details");
      history.append(element("summary", t("查看执行记录")));
      history.ontoggle = async () => {
        if (!history.open) return;
        const old = history.querySelector(".run-history"); old?.remove();
        const list = element("div", undefined, "run-history"); history.append(list);
        try {
          const runs = await api("/agent-tasks/" + task.id + "/runs");
          if (!runs.length) list.append(element("p", t("尚未执行")));
          for (const run of runs) {
            list.append(element("p", stamp(run.occurrence) + " · " + (runLabels[run.status] || run.status) + (run.error_code ? " · " + (errorLabels[run.error_code] || t("执行未完成")) : "")));
            if (run.result?.text) {
              const content = element("div", undefined, "chat-content");
              window.financeRenderMarkdown(content, run.result.text); list.append(content);
            }
          }
        } catch(e) {list.append(element("p", e.message, "danger"));}
      };
      card.append(history); container.append(card);
    }
  };
  async function refreshConnections() {
    if (!workspaceReady) return;
    const [inventory, tasks] = await Promise.all([api("/connectors"), api("/agent-tasks")]);
    const hasConnected = inventory.connections.some(connection => connection.status === "connected");
    const needsReconnect = inventory.connections.some(connection => connection.status === "needs_reconnect");
    $("google-connect").disabled = !inventory.google_configured;
    $("google-connect").hidden = hasConnected || needsReconnect;
    $("google-setup-status").textContent = hasConnected
      ? t("Google 已连接，可在对话里读取邮件和日历，或创建定时任务。仅有读取权限。")
      : needsReconnect
        ? t("Google 授权已失效，请重新连接以恢复邮件与日历读取。")
        : inventory.google_configured
          ? t("连接 Google 后，可在对话里创建邮件与日历任务。只申请读取权限。")
          : t("Google 尚未配置。需要在服务端设置 OAuth Client ID 和 Secret。");
    $("connections-list").replaceChildren();
    for (const connection of inventory.connections) {
      const card = element("article", undefined, "card");
      card.append(element("strong", connection.account), element("p", statusLabels[connection.status] || connection.status),
        element("p", connection.last_sync_at ? t("最近同步 ") + stamp(connection.last_sync_at) : t("尚未同步")));
      if (connection.status !== "disconnected") card.append(button(t("断开连接"), () => api("/connectors/" + connection.id + "/disconnect", "POST")));
      if (connection.status === "needs_reconnect") card.append(button(t("重新连接"), () => $("google-connect").click()));
      $("connections-list").append(card);
    }
    if (!inventory.connections.length) $("connections-list").append(element("p", t("尚未连接账号")));
    window.financeRenderAgentTasks($("agent-task-list"), tasks,
      t("在对话中描述任务和执行时间，例如“每天 8:30 汇总我的邮件和日程”。"));
  }
  $("google-connect").onclick = async () => {
    const popup = window.open("about:blank", "finance-google-connect", "width=560,height=720");
    if (!popup) return message(t("请允许弹窗后重试 Google 连接"), true);
    $("google-connect").disabled = true;
    try {
      const result = await api("/connectors/google/authorize", "POST");
      popup.location = result.url;
    } catch(e) {popup.close(); message(e.message, true);}
    finally {$("google-connect").disabled = false;}
  };
  window.addEventListener("finance-session-ready", () => {
    refreshConnections().catch(e => message(e.message, true));
    clearInterval(poll); poll = setInterval(() => refreshConnections().catch(() => {}), 5000);
  });
  window.addEventListener("finance-session-reset", () => clearInterval(poll));
  window.addEventListener("finance-agent-tasks-updated", () => refreshConnections().catch(() => {}));
})();
