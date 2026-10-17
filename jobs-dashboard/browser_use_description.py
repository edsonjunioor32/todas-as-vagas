"""One-shot browser-use renderer. No Agent, LLM, cloud browser, or API key."""
from __future__ import annotations

import asyncio
import json
import os
import sys

os.environ["ANONYMIZED_TELEMETRY"] = "false"
os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
os.environ["BROWSER_USE_VERSION_CHECK"] = "false"


async def render(url: str, timeout: float, min_chars: int, chromium: str) -> dict:
    from browser_use import Browser
    from description_crawler import extract_description

    browser = Browser(
        headless=True, executable_path=chromium, use_cloud=False,
        enable_default_extensions=False,
    )
    try:
        await browser.start()
        page = await browser.new_page(url)
        await asyncio.sleep(3)
        html = await page.evaluate("() => document.documentElement.outerHTML")
        resolved = await page.get_url()
        title = await page.get_title()
        description, kind = extract_description(
            str(html or "").encode("utf-8")[:4 * 1024 * 1024],
            "text/html", min_chars=min_chars,
        )
        return {"description": description, "kind": kind, "url": resolved, "title": title}
    finally:
        await browser.kill()


def main() -> None:
    url, timeout, min_chars, chromium = sys.argv[1:5]
    result = asyncio.run(asyncio.wait_for(
        render(url, float(timeout), int(min_chars), chromium),
        timeout=float(timeout),
    ))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
