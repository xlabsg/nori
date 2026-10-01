(() => {
  let activeId = "",
    generation = 0,
    connecting;
  const frame = $("desktop-frame"),
    placeholder = $("desktop-placeholder");
  function state(text, connected = false) {
    $("container-status").textContent = text;
    $("environment-connection").textContent = connected ? "已连接" : "未连接";
  }
  function clear() {
    ++generation;
    activeId = "";
    connecting = undefined;
    frame.removeAttribute("src");
    frame.hidden = true;
    placeholder.hidden = false;
    state("等待连接工作区");
  }
  async function connect(force = false) {
    const id = $("conversation-select").value;
    if (!id) throw new Error("请先选择或创建对话");
    if (connecting && id === activeId) {
      await connecting;
      if (!force || id === activeId) return;
    }
    if (id === activeId && !force) return;
    activeId = id;
    const version = ++generation;
    frame.hidden = true;
    frame.removeAttribute("src");
    placeholder.hidden = false;
    state(force ? "正在启动默认 Linux 桌面…" : "正在检查桌面状态…");
    connecting = (async () => {
      try {
        const result = await api(
          "/conversations/" + encodeURIComponent(id) + "/desktop/connect",
          force ? "POST" : "GET",
        );
        if (version !== generation) return;
        if (result.connected === false) {
          activeId = "";
          $("desktop-reconnect").textContent = "启动桌面";
          state("桌面未启动 · 按需使用");
          return;
        }
        $("desktop-reconnect").textContent = "重新连接桌面";
        frame.src = result.url;
        frame.hidden = false;
        placeholder.hidden = true;
        state("正在连接远程画面…");
      } catch (e) {
        if (version === generation) {
          state(e.message);
          activeId = "";
        }
      } finally {
        if (version === generation) connecting = undefined;
      }
    })();
    return connecting;
  }
  window.addEventListener("message", (event) => {
    if (
      event.origin !== location.origin ||
      event.source !== frame.contentWindow ||
      frame.hidden
    )
      return;
    if (event.data?.type === "finance-desktop-connected")
      state("Linux 桌面已连接", true);
    if (event.data?.type === "finance-desktop-disconnected")
      state("桌面连接已断开");
  });
  window.addEventListener("finance-conversation", () => {
    if (!$("conversation-select").value) {
      clear();
      state("桌面未启动 · 按需使用");
      $("desktop-reconnect").textContent = "启动桌面";
    } else connect();
  });
  window.addEventListener("finance-session-ready", async () => {
    const session = sessionVersion;
    try {
      await window.financeConversationReady;
      if (session === sessionVersion) {
        if ($("conversation-select").value) await connect();
        else {
          state("桌面未启动 · 按需使用");
          $("desktop-reconnect").textContent = "启动桌面";
        }
      }
    } catch (e) {
      if (session === sessionVersion) state(e.message);
    }
  });
  window.addEventListener("finance-desktop-used", () => connect());
  window.addEventListener("finance-session-reset", clear);
  const reconnect = $("desktop-reconnect");
  reconnect.onclick = async () => {
    reconnect.disabled = true;
    reconnect.textContent = "正在连接桌面…";
    try {
      await window.financeConnectWorkspace();
      await window.financeEnsureConversation();
      await connect(true);
    } catch (e) {
      state(e.message);
    } finally {
      reconnect.disabled = false;
      reconnect.textContent = "重新连接桌面";
    }
  };
  $("expand-desktop").onclick = () => {
    const expanded = document
      .querySelector(".workspace")
      .classList.toggle("desktop-expanded");
    $("expand-desktop").textContent = expanded ? "收起桌面 ↙" : "展开桌面 ↗";
  };
})();
