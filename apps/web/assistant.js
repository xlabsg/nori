(() => {
  let loaded = false;
  const $a = id => document.getElementById(id);
  const deliveryLabels = {pending: "等待发送", sending: "发送中", sent: "已发送", failed: "发送失败", cancelled: "已取消"};
  async function refresh() {
    if (!workspaceReady) return;
    const state = await api("/assistant/status");
    $a("assistant-services").textContent = state.services.every(s => s.healthy)
      ? "后台运行正常 · 关闭网页后任务仍会执行"
      : "后台服务未就绪，任务可能延迟，请检查本地服务";
    $a("telegram-status").textContent = state.telegram.configured
      ? "Telegram 已配置" + (state.telegram.last_delivery ? " · 最近通知：" + (deliveryLabels[state.telegram.last_delivery.status] || state.telegram.last_delivery.status) : " · 尚未发送通知")
      : "配置后，重要提醒可以发送到 Telegram。";
    $a("telegram-test").hidden = !state.telegram.configured;
    $a("telegram-disconnect").hidden = !state.telegram.configured;
    $a("telegram-save").textContent = state.telegram.configured ? "更新 Telegram" : "连接 Telegram";
    if (!loaded) {
      const prefs = await api("/assistant/preferences");
      $a("assistant-timezone").value = prefs.timezone;
      $a("assistant-quiet").checked = prefs.quiet_enabled;
      $a("assistant-quiet-start").value = prefs.quiet_start;
      $a("assistant-quiet-end").value = prefs.quiet_end;
      $a("assistant-contacts").value = prefs.important_contacts.join("\n");
      $a("assistant-criteria").value = prefs.alert_criteria;
      loaded = true;
    }
  }
  $a("assistant-preferences").onsubmit = async e => {
    e.preventDefault();
    try {
      await api("/assistant/preferences", "PUT", {
        timezone: $a("assistant-timezone").value,
        quiet_enabled: $a("assistant-quiet").checked,
        quiet_start: $a("assistant-quiet-start").value, quiet_end: $a("assistant-quiet-end").value,
        important_contacts: $a("assistant-contacts").value.split("\n").map(s => s.trim()).filter(Boolean),
        alert_criteria: $a("assistant-criteria").value
      });
      message("提醒偏好已保存");
    } catch(e) {message(e.message, true);}
  };
  $a("telegram-form").onsubmit = async e => {
    e.preventDefault();
    const token = $a("telegram-token").value;
    $a("telegram-token").value = "";
    try {
      await api("/assistant/telegram", "PUT", {bot_token: token, chat_id: $a("telegram-chat-id").value.trim()});
      message("Telegram 已保存，可点击发送测试通知确认");
      await refresh();
    } catch(e) {message(e.message, true);}
  };
  $a("telegram-test").onclick = async () => {
    try {await api("/assistant/telegram/test", "POST"); message("测试通知已排队，将遵循免打扰设置发送");}
    catch(e) {message(e.message, true);}
  };
  $a("telegram-disconnect").onclick = async () => {
    try {await api("/assistant/telegram", "DELETE"); await refresh();}
    catch(e) {message(e.message, true);}
  };
  let timer;
  window.addEventListener("finance-session-ready", () => {
    loaded = false; refresh().catch(e => message(e.message, true));
    clearInterval(timer); timer = setInterval(() => refresh().catch(() => {}), 10000);
  });
  window.addEventListener("finance-session-reset", () => {
    clearInterval(timer); loaded = false; $a("telegram-token").value = "";
  });
})();
