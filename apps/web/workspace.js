(() => {
  const workspace = document.querySelector(".workspace");
  document.querySelectorAll("[data-dialog]").forEach((button) => {
    button.onclick = () => $(button.dataset.dialog).showModal();
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.onclick = () => button.closest("dialog").close();
  });
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.onclick = (event) => {
      if (event.target === dialog) {
        const rect = dialog.getBoundingClientRect();
        if (
          event.clientX < rect.left ||
          event.clientX > rect.right ||
          event.clientY < rect.top ||
          event.clientY > rect.bottom
        )
          dialog.close();
      }
    };
  });
  document.querySelector("[data-focus-chat]").onclick = () =>
    $("chat-input").focus();
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.onclick = () => {
      $("chat-input").value = button.dataset.prompt;
      $("chat-input").focus();
    };
  });
  const smallScreen = window.matchMedia("(max-width: 850px)");
  function syncEnvironmentToggle() {
    $("toggle-environment").setAttribute(
      "aria-expanded",
      String(
        smallScreen.matches
          ? workspace.classList.contains("mobile-environment")
          : !workspace.classList.contains("environment-collapsed"),
      ),
    );
  }
  $("toggle-environment").onclick = () => {
    workspace.classList.toggle(
      smallScreen.matches ? "mobile-environment" : "environment-collapsed",
    );
    syncEnvironmentToggle();
  };
  $("close-environment").onclick = () => {
    workspace.classList.remove("mobile-environment");
    workspace.classList.add("environment-collapsed");
    syncEnvironmentToggle();
  };
  smallScreen.addEventListener("change", syncEnvironmentToggle);
  syncEnvironmentToggle();
  document.querySelectorAll("[data-env-tab]").forEach((button) => {
    button.onclick = () => {
      document
        .querySelectorAll("[data-env-tab]")
        .forEach((tab) =>
          tab.setAttribute("aria-selected", String(tab === button)),
        );
      ["desktop", "terminal", "files"].forEach(
        (tab) => ($("env-" + tab).hidden = tab !== button.dataset.envTab),
      );
    };
  });
  window.addEventListener("finance-session-ready", () => {
    $("session-label").textContent = "本地工作区 · 已连接";
  });
  window.addEventListener("finance-session-reset", () => {
    $("session-label").textContent = "本地工作区 · 未连接";
    $("conversation-title").textContent = "Nori";
  });
  window.addEventListener("finance-conversation", () => {
    const select = $("conversation-select");
    $("conversation-title").textContent = select.value
      ? select.selectedOptions[0]?.textContent
      : "Nori";
  });
})();
