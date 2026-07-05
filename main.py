import asyncio
from io import BytesIO
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
import astrbot.api.message_components as Comp
from astrbot.api.star import Context, Star, register
from PIL import Image, ImageSequence

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


DOWNLOAD_TIMEOUT_SECONDS = 45
DOWNLOAD_BACKOFF_BASE_SECONDS = 2
DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_USER_AGENT = "astrbot-plugin-url2img/1.0"
JPEG_QUALITY = 85


@register(
    "astrbot_plugin_url2img",
    "facilisvelox",
    "将模型回复中的图片 URL 自动转换为 JPEG 图片消息；已生成图片只重试下载，不重复触发生图。",
    "1.0.6",
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
                    image_component = await _image_from_url_with_download_retries(
                        segment.value
                    )
                    new_chain.append(image_component)
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


async def _image_from_url_with_download_retries(url: str):
    attempt = 1
    while True:
        try:
            path = await asyncio.to_thread(_download_image_to_temp_file, url)
            if path:
                if attempt > 1:
                    logger.info(
                        f"url2img downloaded image after {attempt} attempt(s): {url}"
                    )
                return Comp.Image.fromFileSystem(path)
        except Exception as exc:
            logger.warning(
                f"url2img image download attempt {attempt} failed, will retry: {url}; {exc}"
            )

        await asyncio.sleep(_download_retry_delay(attempt))
        attempt += 1


def _download_image_to_temp_file(url: str) -> str:
    request = Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        image_bytes = _read_response_bytes(response)
        output_dir = Path(tempfile.gettempdir()) / "astrbot_plugin_url2img"
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="url2img_",
            suffix=".jpg",
            dir=output_dir,
            delete=False,
        ) as tmp_file:
            _write_jpeg_image(image_bytes, tmp_file)
            return tmp_file.name


def _read_response_bytes(response) -> bytes:
    chunks = []
    while True:
        chunk = response.read(DOWNLOAD_CHUNK_SIZE)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _write_jpeg_image(image_bytes: bytes, output_file) -> None:
    with Image.open(BytesIO(image_bytes)) as image:
        frame = next(ImageSequence.Iterator(image)).copy()
        jpeg_image = _image_for_jpeg(frame)
        jpeg_image.save(
            output_file,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True,
            progressive=True,
        )


def _image_for_jpeg(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba_image = image.convert("RGBA")
        background = Image.new("RGBA", rgba_image.size, (255, 255, 255, 255))
        background.alpha_composite(rgba_image)
        return background.convert("RGB")

    return image.convert("RGB")


def _download_retry_delay(attempt: int) -> int:
    return min(DOWNLOAD_BACKOFF_BASE_SECONDS * attempt, 20)
