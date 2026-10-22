# Linux / Windows WSL2 机器节点入口

此入口复用原 CloudWorker、Pro CLI、账号核验、outbox 与云回执，不启动 Owner 工作台，不把 Owner 密钥交给终端。它是机器节点入口；普通众包插件跨端报名、评分界面与跨端 OTA 不能据此宣称全部完成。现有 Mac 参与者流程、身份、进度、评分和 OTA 保持。

## 已验证的精确范围

| 环境 | 当前证据 |
|---|---|
| Linux arm64 Docker | 实际安装、原 Pro 官方账号自检、自动领任务、正文 1 / 评论 95、96 份云回执、20 秒断网后同批回传和任务完成 |
| Linux x64 / 物理 Linux 主机 | 资源与入口已准备，未实机验收 |
| Windows 已有 WSL2 | PowerShell 入口与参数已实现，未在 Windows 宿主执行 |
| Windows 原生 Python | 当前入口不支持；POSIX 锁等依赖尚未替换 |

上述 Linux 验收仅为 `xhs_detail_body_comments_v1`：指定单篇、评论及回复最多 200、media=false，不能外推所有平台、媒体或 300 台实际终端。最终状态和审计原件见[固定交接](../../../../docs/HANDOFF.md)。本轮测试节点验收结束后正常停止，原命名卷、身份和 outbox 保留，不冒长期生产常驻证明。

## 安装输入与启动

使用 Owner 组装并给出准确 `NODE-RUNTIME.json` SHA256 的完整包，不在不完整的源码目录直接执行发行入口。终端须已有 Python 3.12、uv、git，以及合法本地 Pro Python / Signer 源目录；私有 SDK、Cookie 和密钥不随本仓公开分发。安装器按原 `uv.lock` 配依赖，使用 copy 模式，Node 从固定官方地址与摘要安装。

Owner 经正常 `worker_pair` 创建独立机器身份，配置文件只含 `endpoint`、`project_key`、新 `worker_key`，权限 0600。不要复制另一节点的配置或参与身份，也不要放入 `owner_key`。以下路径和摘要均由该节点的实际配置提供：

```sh
/bin/sh install-linux.sh --runtime /完整包/server/crowd/v4/multiplatform \
  --runtime-sha256 <NODE-RUNTIME.json的SHA256> \
  --root "$HOME/.local/share/crowd-node" --cloud-config /本机私有配置.json \
  --sdk-root /本机合法ProPython --signer-root /本机合法Signer --uv /uv绝对路径
/bin/sh bind-linux.sh --root "$HOME/.local/share/crowd-node" --client-id <本机CookieBridge的ClientID>
/bin/sh bind-linux.sh --root "$HOME/.local/share/crowd-node" --client-id <同一ClientID> --status
/bin/sh start-linux.sh --root "$HOME/.local/share/crowd-node" --check
/bin/sh start-linux.sh --root "$HOME/.local/share/crowd-node"
```

安装成功不等于已登录。先在该终端自己的浏览器加载已授权 CookieBridge、仅同步本机，运行 `bind-linux.sh`，由原 Pro 官方 self / AccountSessions 流程生成该节点独立 SID 的认证记录；不能手填 account_ref、复制其他节点状态或伪造 ready。本轮 Docker 复用了宿主原登录，使用审过的临时匿名管道，仅是同机验收设施，不是跨设备 Cookie 共享服务，也不随普通包自动启用。

CookieBridge 本地服务也须按你已购买的原组件说明安装并启动：先 `cd /本机CookieBridge/server`，执行 `uv sync` 后，运行 `uv run python app.py --host 127.0.0.1 --port 8274`。组件和浏览器扩展不随机器节点包分发。`ClientID` 是本机扩展标识，不是 Cookie。已认证的同一绑定直接复用；`bind --status` 仅读原状态，不发 HTTP、不重新认证、不写身份。未核验或结果未知时不会重建 SID 或自动重试认证。

`--check` 只作本地预检，不启动调度或采集；正常 start 沿既有领取循环上报能力、自动领任务和保存回执。SIGTERM 正常关闭调度，保留耐久数据；不要删除 `node-install.json`、身份、outbox 或旧任务来绕过安装冲突。运行日志由启动者保存；本轮私有验收记录和恢复命令在固定交接证据中。当前未提供 systemd / Windows 开机自启或跨 OS OTA 的已验收声明。

## Windows WSL2

在已安装的 WSL2 发行版中运行同一 Linux 包，`windows-wsl.ps1 -Action install|bind|check|start -Distribution Ubuntu ...` 转交原参数。绑定示例：`./windows-wsl.ps1 -Action bind -Distribution Ubuntu -LinuxArguments @('--root','/home/你的用户/.local/share/crowd-node','--client-id','本机ClientID')`。脚本不会自动安装、替换或注销发行版。持久 root、依赖、身份和 outbox 放在 WSL `/home`，不要放在 `/mnt/c`；当前权限保护要求同用户、0700 目录和 0600 私有文件。

Microsoft 官方说明：[安装及检查 WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)、[文件系统与路径](https://learn.microsoft.com/en-us/windows/wsl/filesystems)。WSL2 入口存在不等于 Windows 原生运行或宿主验收通过。
