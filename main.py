import asyncio
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

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


DOWNLOAD_RETRIES = 15
DOWNLOAD_TIMEOUT_SECONDS = 45
DOWNLOAD_BACKOFF_BASE_SECONDS = 2
DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_USER_AGENT = "astrbot-plugin-url2img/1.0"
IMAGE_SUFFIXES = {
    ".apng",
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
CONTENT_TYPE_SUFFIXES = {
    "image/apng": ".apng",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}


@register(
    "astrbot_plugin_url2img",
    "facilisvelox",
    "将模型回复中的图片 URL 自动转换为图片消息。",
    "1.0.3",
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
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        try:
            path = await asyncio.to_thread(_download_image_to_temp_file, url)
            if path:
                if attempt > 1:
                    logger.info(
                        f"url2img downloaded image after {attempt} attempt(s): {url}"
                    )
                return Comp.Image.fromFileSystem(path)
        except Exception as exc:
            last_error = exc
            logger.warning(
                f"url2img image download attempt {attempt}/{DOWNLOAD_RETRIES} failed: {url}; {exc}"
            )

        if attempt < DOWNLOAD_RETRIES:
            await asyncio.sleep(_download_retry_delay(attempt))

    logger.warning(
        f"url2img failed to download image after {DOWNLOAD_RETRIES} attempt(s), "
        f"falling back to URL: {url}; last error: {last_error}"
    )
    return Comp.Image.fromURL(url)


def _download_image_to_temp_file(url: str) -> str:
    request = Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        suffix = _image_suffix_for_download(url, response.headers.get("Content-Type"))
        output_dir = Path(tempfile.gettempdir()) / "astrbot_plugin_url2img"
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="url2img_",
            suffix=suffix,
            dir=output_dir,
            delete=False,
        ) as tmp_file:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                tmp_file.write(chunk)
            return tmp_file.name


def _image_suffix_for_download(url: str, content_type: str | None) -> str:
    path_suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    if path_suffix in IMAGE_SUFFIXES:
        return path_suffix

    if content_type:
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type in CONTENT_TYPE_SUFFIXES:
            return CONTENT_TYPE_SUFFIXES[media_type]

    return ".img"


def _download_retry_delay(attempt: int) -> int:
    return min(DOWNLOAD_BACKOFF_BASE_SECONDS * attempt, 20)
