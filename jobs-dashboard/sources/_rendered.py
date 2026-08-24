# -*- coding: utf-8 -*-
"""Small Selenium helper for public career pages rendered by JavaScript."""
import time


def rendered_links(url, href_pattern, timeout=45):
    """Return unique (href, text) pairs from visible public vacancy links."""
    try:
        from selenium import webdriver
    except ImportError as error:
        raise RuntimeError("Selenium is required for this rendered careers page") from error

    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--disable-gpu", "--disable-extensions", "--window-size=1440,3000",
        "--lang=pt-BR",
    ):
        options.add_argument(argument)
    options.page_load_strategy = "eager"
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = driver.execute_script(
                """
                const pattern = arguments[0];
                const regex = new RegExp(pattern, "i");
                const seen = new Set(), rows = [];
                for (const anchor of document.querySelectorAll("a[href]")) {
                  const href = anchor.href || "";
                  if (!regex.test(href) || seen.has(href)) continue;
                  const text = (anchor.innerText || anchor.textContent || "")
                    .replace(/\\s+/g, " ").trim();
                  if (!text) continue;
                  seen.add(href);
                  rows.push([href, text]);
                }
                return rows;
                """,
                href_pattern,
            )
            if rows:
                return [(str(href), str(text)) for href, text in rows]
            time.sleep(1)
        raise RuntimeError("no public vacancy links after JavaScript rendering")
    finally:
        driver.quit()
