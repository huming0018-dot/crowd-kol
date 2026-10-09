# 授权文件后处理

这是独立于网页采集的本地工具，不联网、不下载平台媒体，不读取浏览器账号或凭据。
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

不会在采集任务中自动下载媒体；可使用下面的独立授权下载工具，或由有权获取的人提供本地文件。删除平台内容时，本系统附属派生证据随内容清理；用户本地原文件不由工具删除。

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
