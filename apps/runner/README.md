# Server Runner

独立部署到用户授权的计算服务器，首版 Linux。通过出站连接领取登记任务，执行参数化程序，回传心跳、日志、产物与结果。禁止默认 root、任意 shell 和 Docker 管理权限。

src/finance_runner/ 计划实现设备注册、租约、执行、取消和产物回传。复用 packages/contracts/ 定义的协议，不导入整个后端。
