# Linux 图形桌面

产品以聊天为主，右侧为真实 Linux 桌面，用户不配置镜像、CPU 或内存。当前平台默认镜像包含 Debian 12、XFCE、Chromium、Python 3、Xvfb、x11vnc 和 noVNC。用户与 Agent 共享同一个对话容器的画面和 `/workspace`。

## 默认软件

| 类别 | 预装工具 | 桌面入口 |
| --- | --- | --- |
| 桌面 | XFCE 应用菜单、任务栏、窗口管理与设置 | 底部“应用”菜单 |
| 浏览与文件 | Chromium、Thunar、File Roller 压缩工具 | 桌面快捷方式 / 应用菜单 |
| 财务表格与文档 | LibreOffice Calc、Writer，PDF 阅读器 Evince | 桌面快捷方式 |
| 编辑与图片 | Mousepad 文本编辑器、Ristretto 图片查看器 | 应用菜单 |
| 分析 | Python 3、pandas、NumPy、Matplotlib、SciPy、requests、pip、venv | Agent 脚本工具 |
| 通用工具 | Git、curl、wget、jq、ripgrep、zip/unzip、less、procps | Agent 脚本工具 |

软件在构建镜像时安装，用户打开工作区即可使用。桌面和下载目录都在临时工作空间内。`pip` 应在工作空间的 venv 中安装额外包；Debian 系统 Python 不支持直接写入系统包。没有开放 root 或运行时系统包安装；增加默认软件修改 Dockerfile 后重建。交易所 CLI 位于后端，账户凭证不放进桌面镜像。

镜像更新只影响新建容器；已有会话保留当前桌面和临时文件。需要新工具时新建对话再连接桌面，不自动删除用户现有容器。

## 本地运行

```sh
docker build -t finance-agent-desktop:local infra/desktop
uv sync
uv run finance-admin migrate
uv run uvicorn finance_agent.entrypoints.api:create_app --factory --host 127.0.0.1 --port 8767
```

保持 Docker Engine 运行。打开或切换对话只检查并连接已有桌面；点击“启动桌面”或 Agent 调用桌面/工作区工具时才启动默认容器。主界面右侧支持真实鼠标、键盘，可点击“展开桌面”扩大画面。不需要为用户提供独立终端入口；`terminal_exec` 保留为 Agent 的内部脚本能力。

图形环境的镜像由服务端准备，服务请求不接受自定义镜像、容器名称、挂载目录或 Docker 参数。默认 2 CPU、4 GB 内存、256 进程，非 root、只读根目录、capabilities 全部移除、禁止提权、不挂载宿主目录或 Docker socket、不注入模型密钥和 API Token。

## 画面与操作

[Xvfb + x11vnc + noVNC](https://github.com/novnc/noVNC) 传输真实桌面画面。FastAPI 代理 noVNC 静态资源与 WebSocket，容器端口仅发布在宿主 `127.0.0.1`。用户取得按对话限定、30 分钟有效的 HttpOnly/SameSite Cookie；Cookie 不出现在 iframe URL。WebSocket 同时检查 Cookie、对话归属、有效期和 Origin。断开工作区撤销该租户的桌面票据，现有代理连接随即关闭。当前票据存在 API 进程内，支持单 API 进程；重启需重新连接，不支持多 worker 的会话共享。

UI 使用 noVNC RFB 的 connect/disconnect 事件显示实际连接状态，画面不是截图占位图。

Pi 的 `desktop_action` 支持 screenshot、click、double_click、move、scroll、type、key。输入坐标限制为固定的 1280×800 桌面，每个动作返回真实 JPEG 截图；Pi 工具把截图转换成模型的 image content，不能只把 base64 当文字发给模型。旧截图只保留最近两张，控制持久上下文大小。操作仍经过当前租户、对话、运行租约与工具集合检查；外部网页内容不能增加权限。用户输入与 Agent 操作当前为协作共享，并未实现独占接管锁。

## 明确限制

- 本地容器原型尚不是生产多租户 microVM 隔离。Chromium 在容器内以 `--no-sandbox` 运行，依赖外层容器边界。上线前应迁移 VM/microVM、启用浏览器沙箱并补全网络策略、资源总配额和回收机制。
- 当前 Docker bridge 允许浏览器联网，尚无目的地址白名单或私网出站过滤。原型只绑定本地 API，不能原样开放为公共桌面服务。
- 临时工作目录 512 MB，容器停止后清空；容器默认最多运行 30 分钟，再次连接会重启环境。文件永久保存、断线任务恢复、音视频与剪贴板文件传输尚未实现。
- 浏览器/桌面的点击、输入及截图工具已实接；已用真实 DeepSeek Flash 验证看图、点击文本框、输入文字并观察结果。用户登录和金融交易由用户接管，当前没有金融动作分类器和事务确认机制。
- 通用桌面动作暂未作为持久后台任务执行，不声称具有所有任务恢复和外部回调语义。

## 验证

```sh
RUN_CONTAINER_TESTS=1 uv run pytest -q
npm --prefix services/agent-runtime run check
npm --prefix services/agent-runtime test
```

真实 Docker 测试验证桌面截图、VNC 协议握手、鉴权代理、跨租户拒绝、错误 Origin、会话撤销，以及内部命令工具的隔离、共享文件和预算。模型循环测试验证工具图像以 image content 传递。真实 DeepSeek Flash + Pi 在合成欢迎页完成截图、定位、点击和输入 `Pi desktop verified`，最终截图已人工检查。

软件镜像验证：真实容器导入 pandas/NumPy/Matplotlib/SciPy/requests 并计算样本总和，启动 LibreOffice Calc 图形窗口；预览中同时打开 Thunar 文件管理器。默认菜单配置参考 [XFCE 官方默认布局](https://github.com/xfce-mirror/xfce4-panel/blob/master/migrate/default.xml.in)。


## 内置 Chrome DevTools MCP

默认镜像预装 Node.js 22 与固定版本 `chrome-devtools-mcp` 1.10.1（npm lockfile）。容器启动时自动打开 Chromium，使用独立 `/workspace/.chromium` profile，启用仅容器内 localhost 可达的 9222 调试端口；不发布该端口到宿主。MCP 通过 `docker exec -i` 在当前对话容器里连接 `http://127.0.0.1:9222`，与用户看到的浏览器共享页签。

Pi 默认可用 `mcp_chrome_*` 工具：页签列表、切换/新建/导航、DOM/可访问性快照、点击、填表、按键、等待、页面脚本、控制台与网络列表。工具 schemas 随版本固定在 `infra/desktop/chrome-tools.json`（在仓库根目录运行 `node scripts/export-chrome-tools.mjs` 可重新导出）；只有第一次实际调用才创建 MCP stdio 进程，并由后端先校验运行租约与当前对话归属，再按需启动桌面。普通对话不会为了 MCP discovery 启动容器。MCP 进程在该轮结束时关闭，Chromium 和桌面继续保留原会话。

当前新镜像只影响新建容器；旧镜像容器继续使用其原有工具，不能在旧容器上宣称 DevTools MCP 可用。后台邮件和日历任务使用 Connector，不依赖此桌面。

配置依据：[Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)。官方只保证 Chrome/Chrome for Testing；Debian Chromium 的兼容性由本仓库的实际集成验证覆盖。

已使用真实 Pi + DeepSeek 完成新容器按需创建、`mcp_chrome_list_pages` 与 `mcp_chrome_take_snapshot` 读取本地欢迎页的验证；验证用临时容器已删除，未操作用户浏览器或账号。
