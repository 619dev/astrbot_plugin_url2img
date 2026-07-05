from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register

try:
    from .openai_img_urls_patch import (
        install_openai_img_urls_patch,
        uninstall_openai_img_urls_patch,
    )
    from .url_parser import SegmentKind, split_image_urls
except ImportError:
    from openai_img_urls_patch import (
        install_openai_img_urls_patch,
        uninstall_openai_img_urls_patch,
    )
    from url_parser import SegmentKind, split_image_urls


@register(
    "astrbot_plugin_url2img",
    "facilisvelox",
    "将模型回复中的图片 URL 自动转换为图片消息。",
    "1.0.2",
)
class Url2ImgPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    async def initialize(self):
        install_openai_img_urls_patch()

    @filter.on_decorating_result()
    async def convert_image_urls(self, event: AstrMessageEvent):
        """Convert image URLs in the outgoing result chain into image components."""
        result = event.get_result()
        if not result or not getattr(result, "chain", None):
            return

        new_chain = []
        converted_count = 0

        for component in result.chain:
            text = _plain_text(component)
            if text is None:
                new_chain.append(component)
                continue

            parsed_segments = split_image_urls(text)
            if not any(segment.kind == SegmentKind.IMAGE_URL for segment in parsed_segments):
                new_chain.append(component)
                continue

            for segment in parsed_segments:
                if segment.kind == SegmentKind.IMAGE_URL:
                    new_chain.append(Comp.Image.fromURL(segment.value))
                    converted_count += 1
                elif segment.value:
                    new_chain.append(Comp.Plain(segment.value))

        if converted_count:
            result.chain = new_chain
            logger.info(f"url2img converted {converted_count} image URL(s).")

    async def terminate(self):
        uninstall_openai_img_urls_patch()


def _plain_text(component) -> str | None:
    if isinstance(component, Comp.Plain):
        return component.text
    if getattr(component, "type", None) == "Plain" and hasattr(component, "text"):
        return component.text
    return None
