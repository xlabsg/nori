const t = window.noriI18n?.t || ((text) => text);
let workspaceReady = false,
  timer,
  refreshing = false,
  sessionVersion = 0,
  lastTasks,
  lastNotes,
  lastMonitors,
  retryRequest;
const $ = (id) => document.getElementById(id);
const state = {
  queued: t("待执行"),
  running: t("执行中"),
  succeeded: t("已完成"),
  partial: t("部分完成"),
  failed: t("失败"),
  cancelled: t("已取消"),
};
const demo = {
  currency: "USD",
  observed_at: new Date().toISOString(),
  source: t("虚构演示数据"),
  opening_equity: "10000",
  closing_equity: "12500",
  cash_flows: [{ kind: "deposit", amount: "2000", external: true }],
  holdings: [
    { asset_id: "bitcoin", quantity: "0.1", price: "60000" },
    { asset_id: "ethereum", quantity: "1", price: "3000" },
    { asset_id: "unpriced-example", quantity: "5", price: null },
  ],
};
$("data").value = JSON.stringify(demo, null, 2);
function message(text, error = false) {
  $("message").textContent = t(text);
  $("message").className = error
    ? "workspace-message danger"
    : "workspace-message";
}
async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok)
    throw new Error(
      typeof data.detail === "string"
        ? t(data.detail)
        : JSON.stringify(data.detail),
    );
  return data;
}
function element(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function action(text, handler) {
  const b = element("button", text);
  b.type = "button";
  b.onclick = async () => {
    const version = sessionVersion;
    b.disabled = true;
    try {
      await handler();
      await refresh();
    } catch (e) {
      if (version === sessionVersion) message(e.message, true);
    } finally {
      b.disabled = false;
    }
  };
  return b;
}
function empty(id, text) {
  $(id).replaceChildren(element("div", text, "empty"));
}
async function refresh() {
  if (!workspaceReady || refreshing) return;
  refreshing = true;
  const version = sessionVersion;
  try {
    const [tasks, notes, monitors, agentTasks] = await Promise.all([
      api("/tasks"),
      api("/notifications"),
      api("/monitors"),
      api("/agent-tasks"),
    ]);
    if (version !== sessionVersion) return;
    $("count").textContent = tasks.length + agentTasks.length;
    $("active").textContent = tasks.filter((t) =>
      ["queued", "running"].includes(t.status),
    ).length + agentTasks.filter(t => ["queued", "retrying", "running"].includes(t.last_run?.status)).length;
    $("unread").textContent = notes.filter((n) => !n.read_at).length;
    $("unread-detail").textContent = $("unread").textContent;
    if (JSON.stringify(tasks) !== lastTasks) {
      lastTasks = JSON.stringify(tasks);
      $("task-list").replaceChildren();
      if (!tasks.length) empty("task-list", t("还没有分析任务。"));
      for (const t of tasks) {
        const c = element("article", undefined, "card");
        c.append(
          element("h3", t.name),
          element("span", state[t.status] || t.status, "status"),
          element(
            "p",
            new Date(t.created_at * 1000).toLocaleString(window.noriI18n?.language) +
              " · " +
              t.input.source,
          ),
        );
        if (t.result) {
          if (t.result.equity)
            c.append(
              element(
                "p",
                t("期间收益 ") +
                  t.result.equity.profit +
                  " " +
                  t.result.currency +
                  t(" · 外部净流入 ") +
                  t.result.equity.external_net_flow,
              ),
            );
          if (t.result.portfolio)
            c.append(
              element(
                "p",
                t("已估值 ") +
                  t.result.portfolio.valued_assets +
                  "/" +
                  t.result.portfolio.total_assets +
                  t(" 项资产 · ") +
                  t.result.portfolio.valued_total +
                  " " +
                  t.result.currency,
              ),
            );
          const details = element("details");
          details.append(
            element("summary", t("查看计算结果与覆盖说明")),
            element("pre", JSON.stringify(t.result, null, 2)),
          );
          c.append(details);
        }
        if (t.error_code)
          c.append(element("p", t("异常：") + t.error_code, "danger"));
        const buttons = element("div", undefined, "row");
        if (["queued", "running"].includes(t.status))
          buttons.append(
            action(t("取消"), () => api("/tasks/" + t.id + "/cancel", "POST")),
          );
        buttons.append(
          action(t("查看事件"), async () => {
            const events = await api("/tasks/" + t.id + "/events");
            c.append(element("pre", JSON.stringify(events, null, 2)));
          }),
        );
        c.append(buttons);
        $("task-list").append(c);
      }
    }
    if (JSON.stringify(notes) !== lastNotes) {
      lastNotes = JSON.stringify(notes);
      $("notifications").replaceChildren();
      if (!notes.length)
        empty("notifications", t("结果就绪后，提醒会出现在这里。"));
      for (const n of notes) {
        const c = element("article", undefined, "card");
        c.append(
          element("h3", n.title),
          element("p", new Date(n.created_at * 1000).toLocaleString(window.noriI18n?.language)),
        );
        if (!n.read_at)
          c.append(
            action(t("标记已读"), () =>
              api("/notifications/" + n.id + "/read", "POST"),
            ),
          );
        $("notifications").append(c);
      }
    }
    if (JSON.stringify(monitors) !== lastMonitors) {
      lastMonitors = JSON.stringify(monitors);
      $("monitor-list").replaceChildren();
      if (!monitors.length) empty("monitor-list", t("尚未创建周期任务。"));
      for (const m of monitors) {
        const c = element("article", undefined, "card");
        c.append(
          element("h3", m.name),
          element(
            "p",
            (m.enabled ? t("已启用") : t("已暂停")) +
              t(" · 每 ") +
              m.interval_seconds +
              t(" 秒 · 固定快照"),
          ),
        );
        if (m.enabled)
          c.append(
            element(
              "p",
              t("下次检查 ") + new Date(m.next_at * 1000).toLocaleString(window.noriI18n?.language),
            ),
          );
        c.append(
          action(m.enabled ? t("暂停") : t("恢复"), () =>
            api("/monitors/" + m.id, "PATCH", { enabled: !m.enabled }),
          ),
        );
        $("monitor-list").append(c);
      }
    }
  } catch (e) {
    if (version === sessionVersion) message(e.message, true);
  } finally {
    refreshing = false;
  }
}
let connectingWorkspace;
window.financeConnectWorkspace = async () => {
  if (workspaceReady) return;
  if (connectingWorkspace) return connectingWorkspace;
  connectingWorkspace = (async () => {
    sessionVersion++;
    const version = sessionVersion;
    clearResults(t("正在连接工作台…"));
    clearInterval(timer);
    try {
      await api("/tasks");
      if (version !== sessionVersion) return;
      workspaceReady = true;
      message("");
      await refresh();
      timer = setInterval(refresh, 5000);
      window.dispatchEvent(new Event("finance-session-ready"));
    } catch (e) {
      workspaceReady = false;
      message(e.message, true);
      throw e;
    } finally {
      connectingWorkspace = undefined;
    }
  })();
  return connectingWorkspace;
};
window.addEventListener("DOMContentLoaded", () => {
  window.financeConnectWorkspace().catch(() => {});
});
function clearResults(text) {
  window.dispatchEvent(new Event("finance-session-reset"));
  for (const id of ["task-list", "notifications", "monitor-list"])
    empty(id, text);
  for (const id of ["count", "active", "unread", "unread-detail"])
    $(id).textContent = "—";
}
$("analysis").onsubmit = async (e) => {
  e.preventDefault();
  $("submit").disabled = true;
  const version = sessionVersion;
  try {
    const input = JSON.parse($("data").value);
    const fingerprint = JSON.stringify({ name: $("name").value, input });
    if (retryRequest?.fingerprint !== fingerprint)
      retryRequest = { fingerprint, key: crypto.randomUUID() };
    await api("/tasks", "POST", {
      name: $("name").value,
      idempotency_key: retryRequest.key,
      input,
    });
    if (version !== sessionVersion) return;
    retryRequest = undefined;
    message(t("任务已入队，结果就绪后将自动提醒。"));
    if ($("repeat").checked) {
      try {
        await api("/monitors", "POST", {
          name: $("name").value,
          interval_seconds: Number($("interval").value),
          input,
        });
        if (version !== sessionVersion) return;
        message(t("分析已入队，周期规则已保存。"));
      } catch (err) {
        if (version === sessionVersion)
          message(t("分析已入队，但周期规则未创建：") + err.message, true);
      }
    }
    await refresh();
  } catch (e) {
    if (version === sessionVersion) message(e.message, true);
  } finally {
    $("submit").disabled = false;
  }
};
$("csv").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const version = sessionVersion;
  try {
    if (file.size > 200000) throw new Error(t("CSV 最大 200 KB"));
    const data = await api("/import/csv", "POST", {
      csv: await file.text(),
      currency: "USD",
      observed_at: new Date().toISOString(),
      source: t("用户导入 CSV"),
    });
    if (version !== sessionVersion) return;
    $("data").value = JSON.stringify(data, null, 2);
    message(t("CSV 已校验，检查数据后提交分析。"));
  } catch (e) {
    if (version === sessionVersion) message(e.message, true);
  }
};
