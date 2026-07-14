import asyncio
from io import BytesIO
import mimetypes
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
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
DOWNLOAD_CHUNK_SIZE = 1024 * 256
DOWNLOAD_USER_AGENT = "astrbot-plugin-url2img/1.0"
JPEG_QUALITY = 85
OUTPUT_MODE_URL_ONLY = "url_only"
OUTPUT_MODE_DOWNLOAD = "download_and_send"


@register(
    "astrbot_plugin_url2img",
    "facilisvelox",
    "将模型回复中的图片 URL 压缩为 JPEG 图片消息，并始终保留原始图片网址。",
    "1.1.0",
)
class Url2ImgPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config if config is not None else {}

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
        found_url = False
        download_images = self.config.get("output_mode", OUTPUT_MODE_DOWNLOAD) != OUTPUT_MODE_URL_ONLY
        compress_images = bool(self.config.get("compress_image", True))

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
                    found_url = True
                    # Keep the source URL first so it remains the primary output.
                    new_chain.append(Comp.Plain(segment.value))
                    if not download_images:
                        continue
                    image_component = await _image_from_url_once(
                        segment.value,
                        compress=compress_images,
                    )
                    if image_component is not None:
                        new_chain.append(image_component)
                        converted_count += 1
                elif segment.value:
                    new_chain.append(Comp.Plain(segment.value))

        if found_url:
            result.chain = new_chain
        if converted_count:
            logger.info(f"url2img converted {converted_count} image URL(s).")

    async def terminate(self):
        uninstall_openai_img_urls_patch()


def _plain_text(component) -> str | None:
    if isinstance(component, Comp.Plain):
        return component.text
    if getattr(component, "type", None) == "Plain" and hasattr(component, "text"):
        return component.text
    return None


async def _image_from_url_once(url: str, *, compress: bool = True):
    try:
        path = await asyncio.to_thread(_download_image_to_temp_file, url, compress)
        if path:
            return Comp.Image.fromFileSystem(path)
    except Exception as exc:
        logger.warning(
            f"url2img image download or compression failed; "
            f"sending source URL only: {url}; {exc}"
        )

    return None


def _download_image_to_temp_file(url: str, compress: bool = True) -> str:
    request = Request(url, headers={"User-Agent": DOWNLOAD_USER_AGENT})
    with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        image_bytes = _read_response_bytes(response)
        output_dir = Path(tempfile.gettempdir()) / "astrbot_plugin_url2img"
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".jpg" if compress else _source_image_suffix(url, response)
        with tempfile.NamedTemporaryFile(
            prefix="url2img_",
            suffix=suffix,
            dir=output_dir,
            delete=False,
        ) as tmp_file:
            if compress:
                _write_jpeg_image(image_bytes, tmp_file)
            else:
                tmp_file.write(image_bytes)
            return tmp_file.name


def _source_image_suffix(url: str, response) -> str:
    content_type = response.headers.get_content_type() if response.headers else None
    suffix = mimetypes.guess_extension(content_type or "")
    if suffix:
        return ".jpg" if suffix == ".jpe" else suffix

    path_suffix = Path(urlsplit(url).path).suffix.lower()
    if path_suffix and len(path_suffix) <= 10:
        return path_suffix
    return ".img"


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
