# astrbot_plugin_url2img

一个轻量的 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 插件，用于把模型回复文本里的图片 URL 自动转换成图片消息发送。

适合接入会在回复末尾附带图片链接的模型、工作流或 Agent。插件会在 AstrBot 发送回复前处理结果链，因此图片 URL 不需要出现在用户消息或主结构体中，只要最终回复文本里有可识别的图片 URL，就会被转换。

## 功能

- 支持文本中的裸图片 URL，例如 `https://example.com/a.png`
- 支持 Markdown 图片语法，例如 `![alt](https://example.com/a.png)`
- 支持图片 URL 出现在回复正文末尾
- 兼容部分 OpenAI 风格服务返回的 `choices[].img_urls`
- 对已生成的图片 URL 增加持续下载重试，避免因跨区下载慢而重复触发生图
- 保留非 URL 文本和原有消息链中的非文本组件
- 无论源图片 URL 是 PNG、WebP、GIF、JPEG 等格式，下载成功后都会统一转换为较小的 JPEG 文件再发送

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

安装并启用后无需额外配置。模型回复类似下面内容时：

```text
这是生成结果：
https://example.com/images/result.png
```

插件会把回复转换为“文本 + 图片”的消息链发送。Markdown 图片也会被识别：

```text
这是生成结果：![result](https://example.com/render?id=123)
```

## 下载重试

当模型或智能体已经成功生成图片，并在回复中返回图片 URL 时，插件会先尝试把图片下载到 AstrBot 所在服务器的临时目录，再发送本地图片文件。这样可以避免 NapCat 或平台适配器直接跨区拉取图片时，因为网络慢或短暂超时导致发送失败。

默认下载策略：

- 已拿到图片 URL 后不会再触发生图请求
- 每个图片 URL 会持续重试下载，直到下载并准备好可发送文件
- 单次下载超时时间为 45 秒
- 重试间隔逐步增加，最长 20 秒
- 重试只针对图片下载，不会再次调用模型或智能体生成图片
- 下载成功后会取图片第一帧，透明背景以白色合成，并以 JPEG 质量 85、优化渐进编码写入临时文件后发送

## 说明

插件通过 AstrBot 的 `on_decorating_result` 事件钩子工作，只修改即将发送的结果链，不会拦截用户消息，也不会主动请求模型。

对于某些 OpenAI 兼容服务，图片生成结果可能不是文本，而是放在原始响应的 `choices[0].img_urls` 中。AstrBot v4.26.2 会把这种“content 为空但 img_urls 有值”的响应判定为无可用输出。本插件会在加载时安装一个很小的兼容补丁，在 AstrBot 判空之前把这类 `img_urls` 注入为 URL 文本，再由本插件转换成图片消息，避免图片生成成功却不发图或留下误导性的空输出错误日志。该补丁会把 OpenAI provider 的单次请求重试限制为 1，避免一次生图命令在兼容恢复前被上游重复提交。

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
[图片消息]
第二张
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
