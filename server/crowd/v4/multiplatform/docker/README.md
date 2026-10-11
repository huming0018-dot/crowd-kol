# Linux/Docker worker

这是自有桥的可运行容器入口。镜像中不打包第三方 MediaCrawler；用户的独立 MC 源码只读挂载，单独 Linux `.venv` 覆盖其 Mac `.venv`，运行目录单独持久化。无 HTTP 服务，无端口发布，不挂浏览器原始 profile、宿主 HOME 或 Docker socket。

默认使用已缓存的 `mcr.microsoft.com/playwright/python:v1.49.0-noble`。镜像有 Python、git 和浏览器运行环境；MC 自身依赖仍需与其要求匹配。用 `CROWD_WORKER_IMAGE` 指定已核实的镜像版本；升级后重跑验收。当前 Linux 桥合成验收不等于七平台登录或真实采集验收。

## 无来源访问的自检

在 `multiplatform` 目录运行：

```bash
bash docker/worker.sh test /absolute/path/to/evidence
python3 docker/verify-lifecycle.py /absolute/path/to/evidence
```

第一步运行自有 `RunnerTest`，排除访问独立 MC 安装的 `InstalledCLI`；所有执行器均为测试生成的替身。第二步使用该自有替身与独立 Linux 环境创建常驻容器，实际执行 `start → status → import` 和 `start → stop → status`，检查只读挂载、network none、无发布端口及持久目录；完成后移除测试容器。证据为 `linux-evidence.json`、`linux-runner-tests.log`、`daemon-lifecycle.json`。替身源码不是第三方代码。

## 用户已有 MC 的启动方式

目录全部使用绝对路径。Linux 环境和 runtime 必须在 MC 源码外，并且不能指向现有 Mac `.venv`、原始浏览器资料或原始采集目录。源码内须已有 `.venv` 目录作为只读嵌套挂载点；不存在时脚本提前拒绝，不替 Docker 自动创建它，以免修改原源码目录。

```bash
bash docker/worker.sh init-env /absolute/linux-env
```

此命令仅用镜像创建 Linux venv，不联网安装第三方依赖。缓存 Playwright 镜像没有 ensurepip，因此使用 `--without-pip` 创建环境，不能声称已经安装 pip 或 MC 依赖。根据用户所用 MC 的 requirements/lock 安装依赖时，应在同一镜像、同一个 `/linux-env` 挂载路径内运行可用的环境管理器，并将 MC 源码只读挂到 `/executor`；不要使用宿主 Mac pip。依赖安装可能需要联网及显式 bootstrap，这一步没有在本次合成验收中执行。`--system-site-packages` 允许复用该镜像的已安装包，不保证与所用 MC 版本完整匹配。Playwright 版本与镜像浏览器必须一致；依赖安装后自行验证这些版本及所用 MC 的启动要求。

```bash
bash docker/worker.sh start /absolute/MediaCrawler /absolute/linux-env /absolute/worker-runtime crowd-linux-worker
printf '{}' | bash docker/worker.sh exec crowd-linux-worker capabilities
printf '{"platform":"xhs","mode":"search","targets":["测试词"],"purpose":"noncommercial_research","max_items":2,"max_api_requests":10}' |
  bash docker/worker.sh exec crowd-linux-worker start
printf '{"run_id":"由start返回的UUID"}' | bash docker/worker.sh exec crowd-linux-worker status
printf '{"run_id":"由start返回的UUID"}' | bash docker/worker.sh exec crowd-linux-worker import
bash docker/worker.sh stop crowd-linux-worker
```

`start` 返回容器 ID，只能证明创建容器；`docker logs crowd-linux-worker` 的 `ready:true` 代表本机路径/Linux Python预检通过。真正任务是否完成须看 `status` 和 `import`。无 MC 依赖的环境不能据 `ready:true` 宣称可生产采集。容器必须常驻：单次 `docker run --rm ... start` 会在主进程退出时终止后台任务，不能替代这个入口。

默认 `network none`，因此不会访问源站。真实采集前在已授权预算内显式设置 `CROWD_WORKER_NETWORK=bridge` 创建新容器；本入口仍没有开放HTTP端口。无头运行只能复用该独立 runtime 中已验证的会话；没有会话时桥返回 `headless_requires_existing_session`。镜像中未提供图形桌面/VNC，二维码、浏览器登录与验证码交互尚未接入，本次不能声称 Linux 登录已跑通。不能自动拷入 Mac profile 或绕过人工登录。

## 生命周期与恢复

- `exec` 支持 capabilities/start/status/stop/import/list，stdin 接收原桥 JSON，保留其预算、会话锁和未知状态语义。
- 常驻 PID 1 回收孤儿 supervisor，收到容器停止信号先请求桥停止活动任务。脚本给15秒停止宽限；非正常强杀仍可能产生未知状态，应核对后人工处理，不能盲目重采。
- 停止容器不删除 runtime。Docker `rm` 只删除容器，下一次以原 runtime 挂载可查询旧结果。
- 只读根文件系统、全部 capabilities 删除、no-new-privileges、宿主UID/GID、256MiB tmpfs和独立 runtime 为默认设置。不执行原MC安装脚本，不修改其源码。
- 挂载路径不可包含逗号（Docker `--mount` 格式限制）。镜像、依赖、真实浏览器登录、长期吞吐和生产接收仍需独立验收。该入口不是云端调度协议或生产部署完成证明。
