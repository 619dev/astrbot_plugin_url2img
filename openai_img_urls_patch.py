from __future__ import annotations

from collections.abc import Iterable
from functools import wraps
from typing import Any

import astrbot.api.message_components as Comp
from astrbot.api import logger


_PATCH_MARK = "_url2img_img_urls_patch_installed"
_PATCH_VERSION = 4
_PATCH_VERSION_ATTR = "_url2img_img_urls_patch_version"
_ORIGINAL_QUERY_ATTR = "_url2img_original_query"


def install_openai_img_urls_patch() -> bool:
    """Let AstrBot treat OpenAI-compatible ``choice.img_urls`` as usable output."""
    try:
        from astrbot.core.message.message_event_result import MessageChain
        from astrbot.core.provider.entities import LLMResponse, TokenUsage
        from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    except Exception as exc:
        logger.warning(f"url2img failed to import OpenAI provider patch targets: {exc}")
        return False

    if (
        getattr(ProviderOpenAIOfficial, _PATCH_MARK, False)
        and getattr(ProviderOpenAIOfficial, _PATCH_VERSION_ATTR, None) == _PATCH_VERSION
    ):
        return True
    if getattr(ProviderOpenAIOfficial, _PATCH_MARK, False):
        uninstall_openai_img_urls_patch()

    original_query = ProviderOpenAIOfficial._query

    @wraps(original_query)
    async def patched_query(self, payloads: dict, tools, *, request_max_retries=None):
        self._url2img_last_completion = None
        _wrap_completion_create(self)
        try:
            return await original_query(
                self,
                payloads,
                tools,
                # Image generation is not idempotent: zero retries means this
                # command reaches the upstream service at most once.
                request_max_retries=0,
            )
        except Exception as exc:
            completion = getattr(self, "_url2img_last_completion", None)
            image_urls = _extract_img_urls(completion)
            valid_urls = [
                url
                for url in image_urls
                if isinstance(url, str) and url.startswith(("http://", "https://"))
            ]
            # Provider exceptions trigger AstrBot's fallback-model loop. Never
            # re-raise an image request: return recovered URLs when available,
            # otherwise turn the failure into a terminal user-facing response.
            output = "\n".join(valid_urls) if valid_urls else "生图失败"
            chain = MessageChain(chain=[Comp.Plain(output)])

            response = LLMResponse(
                role="assistant",
                result_chain=chain,
                raw_completion=completion,
                id=getattr(completion, "id", None),
            )
            usage = getattr(completion, "usage", None)
            if usage:
                response.usage = _extract_usage(self, usage, TokenUsage)

            if valid_urls:
                logger.info(
                    f"url2img recovered {len(valid_urls)} image URL(s) after provider error."
                )
            else:
                logger.warning(
                    "url2img stopped image generation after one failed attempt; "
                    f"fallback models will not be invoked: {type(exc).__name__}: {exc}"
                )
            return response

    original_client_create = ProviderOpenAIOfficial.__init__

    @wraps(original_client_create)
    def patched_init(self, *args, **kwargs):
        original_client_create(self, *args, **kwargs)
        _wrap_completion_create(self)

    setattr(ProviderOpenAIOfficial, _ORIGINAL_QUERY_ATTR, original_query)
    setattr(ProviderOpenAIOfficial, "_url2img_original_init", original_client_create)
    ProviderOpenAIOfficial._query = patched_query
    ProviderOpenAIOfficial.__init__ = patched_init
    setattr(ProviderOpenAIOfficial, _PATCH_MARK, True)
    setattr(ProviderOpenAIOfficial, _PATCH_VERSION_ATTR, _PATCH_VERSION)
    logger.info("url2img installed OpenAI choice.img_urls compatibility patch.")
    return True


def uninstall_openai_img_urls_patch() -> None:
    try:
        from astrbot.core.provider.sources.openai_source import ProviderOpenAIOfficial
    except Exception:
        return

    original_query = getattr(ProviderOpenAIOfficial, _ORIGINAL_QUERY_ATTR, None)
    original_init = getattr(ProviderOpenAIOfficial, "_url2img_original_init", None)
    if original_query:
        ProviderOpenAIOfficial._query = original_query
    if original_init:
        ProviderOpenAIOfficial.__init__ = original_init
    if hasattr(ProviderOpenAIOfficial, _ORIGINAL_QUERY_ATTR):
        delattr(ProviderOpenAIOfficial, _ORIGINAL_QUERY_ATTR)
    if hasattr(ProviderOpenAIOfficial, "_url2img_original_init"):
        delattr(ProviderOpenAIOfficial, "_url2img_original_init")
    setattr(ProviderOpenAIOfficial, _PATCH_MARK, False)
    if hasattr(ProviderOpenAIOfficial, _PATCH_VERSION_ATTR):
        delattr(ProviderOpenAIOfficial, _PATCH_VERSION_ATTR)


def _wrap_completion_create(provider: Any) -> None:
    completions = getattr(getattr(provider.client, "chat", None), "completions", None)
    if completions is None:
        return

    original_create = getattr(completions, "create", None)
    if original_create is None:
        return
    if getattr(original_create, "_url2img_wrapped", False):
        if getattr(original_create, "_url2img_wrapper_version", None) == _PATCH_VERSION:
            return
        original_create = getattr(original_create, "__wrapped__", original_create)

    @wraps(original_create)
    async def wrapped_create(*args, **kwargs):
        completion = await original_create(*args, **kwargs)
        _inject_img_urls_as_message_content(completion)
        provider._url2img_last_completion = completion
        return completion

    setattr(wrapped_create, "_url2img_wrapped", True)
    setattr(wrapped_create, "_url2img_wrapper_version", _PATCH_VERSION)

    try:
        completions.create = wrapped_create
    except Exception as exc:
        logger.warning(f"url2img failed to wrap OpenAI completions.create: {exc}")


def _extract_img_urls(completion: Any) -> list[str]:
    urls: list[str] = []
    choices = getattr(completion, "choices", None)
    if not isinstance(choices, Iterable):
        return urls

    for choice in choices:
        urls.extend(_coerce_str_list(getattr(choice, "img_urls", None)))
        urls.extend(_coerce_str_list(getattr(choice, "image_urls", None)))
        message = getattr(choice, "message", None)
        urls.extend(_coerce_str_list(getattr(message, "img_urls", None)))
        urls.extend(_coerce_str_list(getattr(message, "image_urls", None)))

    return _dedupe(urls)


def _inject_img_urls_as_message_content(completion: Any) -> None:
    choices = getattr(completion, "choices", None)
    if not isinstance(choices, Iterable):
        return

    for choice in choices:
        message = getattr(choice, "message", None)
        if message is None:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            continue

        urls = _dedupe(
            [
                *_coerce_str_list(getattr(choice, "img_urls", None)),
                *_coerce_str_list(getattr(choice, "image_urls", None)),
                *_coerce_str_list(getattr(message, "img_urls", None)),
                *_coerce_str_list(getattr(message, "image_urls", None)),
            ],
        )
        valid_urls = [
            url
            for url in urls
            if isinstance(url, str) and url.startswith(("http://", "https://"))
        ]
        if not valid_urls:
            continue

        try:
            message.content = "\n".join(valid_urls)
        except Exception as exc:
            logger.warning(f"url2img failed to inject img_urls into content: {exc}")


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [item for item in value if isinstance(item, str)]
    return []


def _dedupe(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _extract_usage(provider: Any, usage: Any, token_usage_type: type):
    extractor = getattr(provider, "_extract_usage", None)
    if callable(extractor):
        try:
            return extractor(usage)
        except Exception:
            pass
    return token_usage_type()
