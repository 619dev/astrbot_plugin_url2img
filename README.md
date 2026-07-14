# astrbot_plugin_url2img

一个轻量的 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件，可只返回模型回复中的图片 URL，也可下载图片并作为图片消息发送，并始终保留原始图片网址。

适合接入会在回复末尾附带图片链接的模型、工作流或 Agent。插件会在 AstrBot 发送回复前处理结果链，因此图片 URL 不需要出现在用户消息或主结构体中，只要最终回复文本里有可识别的图片 URL，就会被转换。

## 功能

- 支持文本中的裸图片 URL，例如 `https://example.com/a.png`
- 支持 Markdown 图片语法，例如 `![alt](https://example.com/a.png)`
- 支持图片 URL 出现在回复正文末尾
- 兼容部分 OpenAI 风格服务返回的 `choices[].img_urls`
- 对已生成的图片 URL 只尝试下载一次，避免跨区下载失败时阻塞回复或重复触发生图
- 保留非 URL 文本和原有消息链中的非文本组件
- 可选择将源图片压缩为 JPEG，或保留原始文件发送
- 无论图片下载和压缩是否成功，都会在回复中保留原始图片网址

## 安装

将本插件目录放到 AstrBot 的插件目录：

```text
AstrBot/data/plugins/astrbot_plugin_url2img
```

然后在 AstrBot WebUI 的插件管理页重载插件，或重启 AstrBot。

本插件转换图片格式需要 Pillow。如果插件环境没有自动安装依赖，请在 AstrBot 的 Python 环境中安装：

```bash
pip install -r requirements.txt
```

## 使用方式

安装并启用后，默认采用“下载并发送 + 压缩图片”。模型回复类似下面内容时：

```text
这是生成结果：
https://example.com/images/result.png
```

插件会把回复转换为“文本 + 原始网址 + 压缩图片”的消息链发送。Markdown 图片也会被识别：

```text
这是生成结果：![result](https://example.com/render?id=123)
```

## 配置

AstrBot 会根据插件目录中的 `_conf_schema.json` 在 WebUI 生成配置界面：

- `output_mode`：图片输出模式
  - `url_only`：完全不下载文件，只返回图片 URL
  - `download_and_send`：保留 URL，并下载、发送图片消息（默认）
- `compress_image`：是否压缩图片，默认开启；仅在 `download_and_send` 模式生效
- `generation_timeout_seconds`：等待生图服务返回 URL 的超时时间，默认 600 秒；延长等待不会增加请求次数

修改后保存配置并重载插件。关闭压缩时，插件会原样保存下载内容并发送，不进行格式转换或重新编码。

## 下载与压缩

当模型或智能体已经成功生成图片，并在回复中返回图片 URL 时，插件会先尝试把图片下载到 AstrBot 所在服务器的临时目录，再发送本地图片文件。这样可以避免 NapCat 或平台适配器直接跨区拉取图片时，因为网络慢或短暂超时导致发送失败。

默认下载策略：

- 已拿到图片 URL 后不会再触发生图请求
- 每个图片 URL 只尝试下载一次，不进行重试
- 单次下载超时时间为 45 秒
- 下载过程不会再次调用模型或智能体生成图片
- 开启压缩时，下载成功后会取图片第一帧，透明背景以白色合成，并以 JPEG 质量 85、优化渐进编码写入临时文件后发送
- 关闭压缩时，不解码或重新编码图片，直接发送下载到的原始文件
- 下载或压缩失败时跳过图片消息，直接用原始图片网址保底；成功时也会附带该网址
- 上游请求报错时优先返回响应中已有的图片 URL；没有 URL 则只回复“生图失败”
- 生图请求只提交一次，不进入 AstrBot 的回退对话模型链

## 说明

插件通过 AstrBot 的 `on_decorating_result` 事件钩子工作，只修改即将发送的结果链，不会拦截用户消息，也不会主动请求模型。

对于某些 OpenAI 兼容服务，图片生成结果可能不是文本，而是放在原始响应的 `choices[0].img_urls` 或其他响应尾部字段中。AstrBot 会把这种“content 为空但 img_urls 有值”的响应判定为无可用输出。本插件会在 AstrBot 判空之前递归提取并注入这类图片 URL，再转换成图片消息。补丁将 AstrBot 的总尝试次数设为 1，同时关闭 OpenAI Python SDK 自身的内层重试；失败会被转换为终止响应，不会把同一条生图命令继续提交给回退模型。

如果上游发生纯连接超时且没有向客户端返回任何响应字节，客户端无法取得只存在于服务端的图片 URL，此时会回复“生图失败”。如果异常对象仍带有 `body`、HTTP response、completion 或尾部 `img_urls`，插件会优先从中恢复图片 URL。

AstrBot OpenAI provider 默认超时通常为 120 秒。插件默认将生图请求的等待时间延长到 600 秒，让耗时较长的服务能在连接断开前返回图片 URL；AstrBot 与 OpenAI SDK 的重试仍保持关闭。

转换规则：

- 裸 URL 需要以常见图片扩展名结尾，如 `.jpg`、`.png`、`.gif`、`.webp` 等，允许带查询参数。
- Markdown 图片语法中的 URL 会被视为图片 URL，即使路径没有图片扩展名。
- 普通网页 URL 会保留为文本，避免误发成图片。

当前支持的裸 URL 图片扩展名：

```text
.apng .avif .bmp .gif .jpeg .jpg .png .svg .webp
```

## 示例

输入回复：

```text
已完成，图片在这里：https://cdn.example.com/out.webp
```

发送效果：

```text
已完成，图片在这里：
https://cdn.example.com/out.webp
[图片消息]
```

输入回复：

```text
第一张 https://cdn.example.com/a.jpg
第二张 ![b](https://cdn.example.com/b)
```

发送效果：

```text
第一张
https://cdn.example.com/a.jpg
[图片消息]
第二张
https://cdn.example.com/b
[图片消息]
```

## 开发与测试

语法检查：

```bash
python3 -m py_compile url_parser.py main.py openai_img_urls_patch.py
```

运行解析器样例测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c "import test_url_parser as t; [getattr(t, name)() for name in dir(t) if name.startswith('test_')]; print('parser tests passed')"
```

如果本地安装了 `pytest`，也可以运行：

```bash
pytest -q
```

## 许可协议

本项目使用 [MIT License](./LICENSE) 开源。

选择 MIT 的原因是它足够宽松，适合小型机器人插件：允许个人或商业场景自由使用、修改和分发，只需要保留版权和许可声明。
