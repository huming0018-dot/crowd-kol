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

## 常用安装入口

发行包内执行 `sh install-linux.sh`；标准安装会自动取包清单摘要和默认目录，不需要填写 runtime SHA、uv 或 Python 路径。已有节点可运行 `sh install-linux.sh --root /原安装目录 --check`，从原安装记录读取 Pro、Signer、Python 和采集目录，不重复下载工具或重做登录。`sh bind-linux.sh --root /原安装目录 --status` 会直接复用原 SID；不再要求手填 ClientID。首次绑定在原本地 Bridge 中只有一个已连接小红书客户端时自动选择，有歧义则保留状态并提示选择，不能猜账号。

缺失 uv / Python 3.12 时，入口使用固定发布摘要的公共工具及受管 Python。自动发现安装包旁 `bootstrap-cache` 中的 uv、Python 和 Node 官方归档，显式 `--bootstrap-cache` 优先；Node 仍由原资源校验流程验证归档、文件和许可证。已有工具优先复用，不修改 shell profile。未缓存的 Node 下载仍只有单次网络读取超时，没有整个下载的总期限；本轮缓存接入不冒称修复了这一上界。Git 仅在已有 root 或无密码 sudo 权限时由原系统包管理器安装，不索密码。默认 Debian 官方 HTTP 源在本轮容器中下载主索引失败；安装器仅为原默认源创建同源 HTTPS 临时副本，保留签名和原系统源，自定义源不改。APT 索引失败立即停止；索引总时限180秒、安装600秒、APT单连接20秒。独立缺工具容器已确认 Git/curl/CA 安装及工具检查成功（该次工具阶段整体记录约33秒、同依赖再次检查约1秒）。随后主动终止后续下载，整个工具测试入口保留exit2，不称完整安装成功，也不当作独立APT性能benchmark或所有网络环境的保证。

Owner 仍需通过正常配对提供该节点的私有配置，并在本机准备合法 Pro / Signer / CookieBridge；安装器会自动发现支持的目录和原安装记录，但不会公开附带私仓、复制其他节点账号或静默新建身份。缺少这些输入时会明确停止；本轮新 HOME、已有系统 Python/Git 的隔离节点用同一发行入口和邻接公开缓存完成全部节点依赖安装，约29秒；随后正常绑定复用本机原浏览器登录，约7秒，再次绑定保留同 SID 和 generation。Owner 提供合法组件和独立配对配置仍是前置，不能与另一空工具容器的证据拼成“完全空OS一次安装”。Windows 宿主仍未验收。下面是 Owner 的高级输入说明，已有节点不需逐项填写。

## 安装输入与启动

使用 Owner 组装并给出准确 `NODE-RUNTIME.json` SHA256 的完整包，不在不完整的源码目录直接执行发行入口。入口会检查并在具备权限和下载条件时补公共工具；合法本地 Pro Python / Signer 源目录仍由 Owner 准备；私有 SDK、Cookie 和密钥不随本仓公开分发。安装器按原 `uv.lock` 配依赖，使用 copy 模式，Node 从固定官方地址与摘要安装。

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

正常入口会按已配置的本地组件准备 Bridge 依赖并复用／启动原服务。仅供 Owner 手工排查：在 `/本机CookieBridge/server` 按原组件说明安装依赖后，使用 `APP_HOST=127.0.0.1 APP_PORT=8274 uv run python app.py`。已核原 app.py 定义 Tornado 选项但未解析命令行，不能靠 `--host` 保证回环监听；新入口使用原环境变量。组件和浏览器扩展不随机器节点包分发。`ClientID` 是本机扩展标识，不是 Cookie。已认证的同一绑定直接复用；`bind --status` 仅读原状态，不发 HTTP、不重新认证、不写身份。未核验或结果未知时不会重建 SID 或自动重试认证。

`--check` 只作本地预检，不启动调度或采集；正常 start 沿既有领取循环上报能力、自动领任务和保存回执。SIGTERM 正常关闭调度，保留耐久数据；不要删除 `node-install.json`、身份、outbox 或旧任务来绕过安装冲突。运行日志由启动者保存；本轮私有验收记录和恢复命令在固定交接证据中。当前未提供 systemd / Windows 开机自启或跨 OS OTA 的已验收声明。

## Windows WSL2

在已安装的 WSL2 发行版中运行同一 Linux 包，`windows-wsl.ps1 -Action install|bind|check|start -Distribution Ubuntu ...` 转交原参数。绑定示例：`./windows-wsl.ps1 -Action bind -Distribution Ubuntu -LinuxArguments @('--root','/home/你的用户/.local/share/crowd-node','--client-id','本机ClientID')`。脚本不会自动安装、替换或注销发行版。持久 root、依赖、身份和 outbox 放在 WSL `/home`，不要放在 `/mnt/c`；当前权限保护要求同用户、0700 目录和 0600 私有文件。

Microsoft 官方说明：[安装及检查 WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)、[文件系统与路径](https://learn.microsoft.com/en-us/windows/wsl/filesystems)。WSL2 入口存在不等于 Windows 原生运行或宿主验收通过。
