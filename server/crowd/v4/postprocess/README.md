# 授权文件后处理

这是独立于网页采集的本地工具。OCR、字幕整理与ASR处理不联网；媒体下载及初次模型下载仅由明确调用启动，不读取浏览器账号或凭据。
输出JSON在插件「指定KOL → 导入获授权的OCR/字幕转录/汇总画像」中预览、确认后上传。必须先有同一参与身份收到的对应内容；派生结果与原文分开。

## Mac图片OCR

需要Python 3。发布包附带通用 `crowd-vision`（macOS14+）；源码运行可使用已安装的Swift命令行工具。

```sh
python3 evidence.py --kind ocr --input /绝对路径/授权图片.png \
  --platform xiaohongshu --content-id 24位笔记ID \
  --authorization-ref 创作者授权文件编号 --output /绝对路径/ocr-evidence.json
```

每次最多2图，每图25MB。输出包括图像字节SHA256、文字、0–1识别置信度、归一化文字框及截断标记。坐标原点为图像左下角。最多200个文字块、每块2000字、汇总正文24000字，发生截断明确标记。空结果可能是图中无可识别文字，不等于页面没有价格。

每个文字块默认 `semantic_type=unclassified`、`review_status=unreviewed`。OCR分数不是事实准确率，菜品单价/套餐价/人均价必须分别人工核对，不自动把菜单价格写成客单价。

## 已有字幕或转录

```sh
python3 evidence.py --kind transcript --input /绝对路径/授权字幕.vtt \
  --platform bilibili --content-id BV1xx411c7mD \
  --authorization-ref 创作者授权文件编号 --output /绝对路径/transcript-evidence.json
```

支持UTF-8 TXT/VTT/SRT，保留时间轴原文，上限24000字。此模式只导入已有字幕/转录。自动识别使用下面独立的asr模式。不将视频简介冒充转录。

## 作者授权汇总画像

输入JSON只能包含：

```json
{
  "population": "创作者授权的后台统计总体",
  "dimension": "地区",
  "sample_size": 100,
  "coverage_period": "2026-10-01/2026-10-07",
  "aggregate_values": {"上海": 20, "其他": 80}
}
```

使用 `--kind demographics`。不接收个人名单、账号ID、手机号或其他逐人数据。授权引用是用户声明，服务端明确标记尚未独立核实。没有作者授权来源时不生成画像，也不把评论样本当全部粉丝。

## 文件与故障

输出新建为0600，不覆盖已有文件。选择另一个输出文件名可保留历史。超过大小/不支持格式/授权引用为空时停止，不产生伪完成结果。Vision受系统权限限制时返回本地处理失败；不会自动上传图片或降级使用云端OCR。

不会在采集任务中默认下载媒体。插件发现当前内容的公开媒体引用后，可导出获授权媒体任务，用下面的独立流水线完成下载及处理，也可由有权获取的人提供本地文件。删除平台内容时，本系统附属派生证据随内容清理；用户本地原文件不由工具删除。

## 独立授权媒体下载

```sh
python3 media.py --url 'https://允许的公开CDN/资源路径' --authorization-ref 授权文件编号 --output-dir ./authorized-assets
```

最多2个资源、每个25MB；仅接受xhscdn.com、xhsimg.com、hdslb.com及其子域的公开HTTPS图片/音频/视频。每次跳转重查域名和公有地址，连接绑定已验证IP，不用Cookie、账号密码或私有请求头。分段DASH/HLS、需认证的链接和过期链接不在此模式支持范围。资源不完整、超限或类型不支持会保留明确失败，不绕过限制。

## 有条件的本机自动转录

```sh
./crowd-speech --check
# 如系统支持中文离线模型，由本人明确授权并提供一段有权处理的音频：
./crowd-speech --authorize /绝对路径/音频.wav
python3 evidence.py --kind asr --input /绝对路径/音频.wav \
  --platform bilibili --content-id BV1xx411c7mD \
  --authorization-ref 授权文件编号 --output /绝对路径/asr-evidence.json
```

本版限中文、每份音频不超过60秒。需要macOS本机中文识别模型和系统语音识别权限；缺任一条件返回明确失败，绝不改用云端识别。输出为未作语义核验的派生转录，不能替代原文。实现同时检查 `supportsOnDeviceRecognition` 并设置 `requiresOnDeviceRecognition=true`，依据[Apple设备端支持说明](https://developer.apple.com/documentation/speech/sfspeechrecognizer/supportsondevicerecognition)和[本机识别请求说明](https://developer.apple.com/documentation/speech/sfspeechrecognitionrequest/requiresondevicerecognition)。

本次Mac现场：Vision OCR合成图片实跑通过；Speech通用二进制编译通过，`--check`返回中文离线模型不可用、语音权限未准。没有申请系统权限、下载模型或假报实际音频转录成功。Intel仅完成通用编译，待独立硬件验收。

## 4.2.5：不依赖苹果语音授权的本地转写

新增独立的 Faster Whisper CPU 路径。首次设置需要网络下载依赖和约78MB固定版本tiny模型；此后转录只读本地文件，不上传音频，不自动调用云服务。模型文件随附SHA清单，每次加载校验；不自动加载任意Hub模型或用户token。tiny只是轻量中文基线，存在错字，结果必须审核，不承诺98%语音准确率。

在本目录运行（Python 3.9+；已实测Apple芯片Mac，其他硬件须单独验收）：

```sh
python3 -m venv .asr-venv
.asr-venv/bin/python -m pip install -r requirements-asr.txt
python3 fetch_model.py --output-dir ./asr-model-tiny
.asr-venv/bin/python evidence.py --kind asr --input /绝对路径/授权音频.wav \
  --platform bilibili --content-id BV1xx411c7mD \
  --authorization-ref 创作者授权文件编号 --asr-model ./asr-model-tiny \
  --output /绝对路径/asr-evidence.json
```

已存在模型目录时不重新下载，不覆盖；转录会校验原清单。解码仅限本地支持的音视频容器，禁止播放列表/外部协议。原单片转录器最多25MB、60秒、单进程150秒；下述长媒体路径按55秒窗口调用它。支持MP4/WebM中的音轨，但不自动获取需要登录或分段协议的源视频。输出时间段和原始识别文字，明确 `processor=faster_whisper_local`。

依据：[Faster Whisper官方项目及MIT许可](https://github.com/SYSTRAN/faster-whisper)、[固定模型版本](https://huggingface.co/Systran/faster-whisper-tiny/tree/d90ca5fe260221311c53c58e660288d3deb8d356)。我们提供调用代码，安装时获取官方依赖；安装包不包含这些第三方库或模型。既有Apple Speech仍可选择，不自动降级或替用户弹权限请求。

## 4.2.5：从插件媒体任务到可导入证据

1. 在指定KOL内容的详情中，确认媒体权利并导出媒体任务JSON。只有本次DOM实际可见、受支持CDN的公开引用才会列出；blob/凭证URL/不可访问资源不伪造替代链接。
2. 运行下列命令。默认只下载；`--ocr`只处理图片，`--asr`只处理音视频，并要求显式本地模型目录。

```sh
.asr-venv/bin/python pipeline.py --manifest /绝对路径/媒体任务.json \
  --output-dir /绝对路径/新的处理目录 --ocr --asr --asr-model ./asr-model-tiny
```

不需要ASR时可用普通 `python3 pipeline.py ... --ocr`。每任务最多2资源×25MB，逐个下载、处理、落独立回执；第一份成功不会因第二份失败丢失。来源URL不写进处理结果日志。已有输出目录拒绝覆盖；失败重试使用新目录。下载成功而处理失败时保留本地文件，随后可直接运行 `evidence.py`，不重复下载。

3. 将 `asset-1/evidence.json`、`asset-2/evidence.json` 中实际成功的文件依次导入插件；下载文件本身不上传。`manifest.json`及逐项`receipt-N.json`记录下载、处理或失败，不把“下载成功”记成“已入库”。没有对应内容时先完成原文入库。

现场证据：2026-10-09在Apple芯片Mac用自制中文音频完成Faster Whisper本地转录。识别有错字，属于工作链路验证；不是生产音频语义质量验收。媒体网络边界与部分失败已做隔离测试，实际平台CDN/真实媒体仍须逐源验证。

## 长视频与可恢复本地转录

`long_media.py` 复用原本地模型转录器。普通 PCM WAV 可由标准库处理；其他音视频需要明确配置音频解码完整的 FFmpeg。Playwright 自带 FFmpeg 仅用于录像，不支持本路径所需音轨解码，不能用来声称抽轨可用。

```sh
export CROWD_FFMPEG=/绝对路径/完整的ffmpeg
.asr-venv/bin/python long_media.py --input /绝对路径/已有授权视频.mp4 \
  --asr-model /绝对路径/已验证本地模型 --work-dir /绝对路径/独立转录检查点 \
  --platform bilibili --content-id BV1xx411c7mD --authorization-ref 本地素材授权 \
  --output /绝对路径/新的转录结果.json
```

输入仍最多25MiB，音轨最多3600秒；抽取16kHz单声道PCM，分为55秒窗口，相邻重叠2秒。每片结果先原子持久化，再开始下一片。时间戳转为原素材的绝对秒；仅对时间重叠且文本规范化相同的片段去重，不做语义猜测，也不会删除不同时间重复说的话。静音或无识别文字的窗口另计数，其他窗口结果保留。

检查点包括输入SHA、每片音频SHA、模型清单SHA和处理代码版本。取消/失败保留原任务的专用副本、音轨和已完成片段；重新执行同一检查点复用已验证片段。模型、代码、输入或缓存损坏时明确拒绝复用。CLI SIGTERM/INT或工作台取消终止处理；工作台 `MediaJobs.resume(job_id)` 恢复同一已取消/失败任务，不重新下载原视频。原始素材只读。工作台成功后删除输入副本，保留派生音轨/检查点；1小时音轨及重叠片段合计可能约230MB，须为独立运行目录留足空间。

工作台沿用 `kind=asr`，新增 `completed_chunks`、`total_chunks`、`checkpoint_available` 进度及恢复入口。缺模型时返回 `local_asr_model_not_configured`，能力状态 `local_model_unavailable`；缺FFmpeg时仅支持兼容PCM WAV。库的缺模型处理状态为 `model_unavailable`，不伪造转录文本、不下载模型或自动外发音视频。正文预览仍有24000字上限，完整结构化时间轴单独保留，`truncated` 明确标记预览裁剪；转录完整性与识别质量仍需人工检查。

本轮真实本机验证使用70秒自制音调视频，验证FFmpeg抽轨、两片分段、绝对时间、重叠去重、断点复用与原文件SHA不变。ASR片段文字使用明确的离线替身，以验证合并算法；没有冒充实际模型识别。

```sh
CROWD_FFMPEG=/绝对路径/完整的ffmpeg python3 verify_long_media.py --output-dir /绝对路径/新验证目录
```
### 分段ASR时标边界

本地provider尾段end若超实际音轨不超过0.5秒、start仍在音轨内，可裁到实际结尾；原文本及原provider时标保存在timing_adjustments。这是产品有界容错策略，不是模型精度保证。更大越界、倒序、非有限值仍失败。短证据及长缓存均校验并保留调整，长结果标明chunk局部与绝对秒数。源码/模型哈希改变后旧缓存明确身份失配，不自动重算未知任务；保持原检查点，使用新的处理任务。
