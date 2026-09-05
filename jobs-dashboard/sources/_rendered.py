# -*- coding: utf-8 -*-
"""Small Selenium helpers for public career pages rendered by JavaScript."""
import re
import time


def _webdriver():
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
    return webdriver.Chrome(options=options)


def _visible_links(driver, href_pattern):
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
    ) or []
    return [(str(href), str(text)) for href, text in rows]


def rendered_links(url, href_pattern, timeout=45):
    """Return unique (href, text) pairs from visible public vacancy links."""
    driver = _webdriver()
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rows = _visible_links(driver, href_pattern)
            if rows:
                return rows
            time.sleep(1)
        raise RuntimeError("no public vacancy links after JavaScript rendering")
    finally:
        driver.quit()


def _next_pagination_control(driver):
    """Return the next enabled pagination control from common public boards."""
    return driver.execute_script(
        r"""
        const visible = element => {
          if (!element) return false;
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" &&
            rect.width > 0 && rect.height > 0;
        };
        const disabled = element => {
          if (!element) return true;
          const parent = element.closest("li");
          return element.disabled || element.getAttribute("aria-disabled") === "true" ||
            element.classList.contains("disabled") ||
            (parent && parent.classList.contains("disabled"));
        };
        const label = element => [
          element.getAttribute("aria-label") || "",
          element.getAttribute("title") || "",
          element.innerText || element.textContent || ""
        ].join(" ").replace(/\s+/g, " ").trim().toLowerCase();

        const explicit = [...document.querySelectorAll('a[rel="next"],button[rel="next"]')]
          .find(element => visible(element) && !disabled(element));
        if (explicit) return explicit;

        const containers = [
          ...document.querySelectorAll(
            'nav, ul.pagination, .pagination, [class*="pagination"], [aria-label*="pag"]'
          )
        ];
        const candidates = [];
        for (const container of containers) {
          for (const element of container.querySelectorAll("a,button")) {
            if (!visible(element) || disabled(element)) continue;
            const text = label(element);
            if (/pr[oó]xim|next/.test(text) || /^(>|›|»)$/.test(text)) {
              candidates.push(element);
            }
          }
        }
        if (candidates.length) return candidates[0];

        const active = document.querySelector(
          'li.active, li.page-item.active, [aria-current="page"]'
        );
        if (active) {
          let sibling = active.nextElementSibling;
          while (sibling) {
            const element = sibling.matches("a,button")
              ? sibling : sibling.querySelector("a,button");
            if (element && visible(element) && !disabled(element)) return element;
            sibling = sibling.nextElementSibling;
          }
        }
        return null;
        """
    )


def rendered_paginated_links(url, href_pattern, timeout=120, max_pages=100):
    """Collect vacancy links across a JavaScript-rendered paginated board.

    The helper follows the board's visible "next" control instead of guessing
    query-string parameters. It stops when there is no enabled next control,
    when a page repeats, or when ``max_pages`` is reached.
    """
    driver = _webdriver()
    try:
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        deadline = time.monotonic() + timeout
        collected = {}
        seen_pages = set()

        for _ in range(max_pages):
            rows = []
            while time.monotonic() < deadline:
                rows = _visible_links(driver, href_pattern)
                if rows:
                    break
                time.sleep(0.5)
            if not rows:
                raise RuntimeError("no public vacancy links after JavaScript rendering")

            fingerprint = tuple(sorted(href for href, _text in rows))
            if fingerprint in seen_pages:
                break
            seen_pages.add(fingerprint)
            for href, text in rows:
                collected.setdefault(href, text)

            control = _next_pagination_control(driver)
            if control is None:
                break

            previous_url = driver.current_url
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", control
            )
            driver.execute_script("arguments[0].click();", control)

            changed = False
            while time.monotonic() < deadline:
                time.sleep(0.25)
                current = _visible_links(driver, href_pattern)
                current_fingerprint = tuple(sorted(href for href, _text in current))
                if current_fingerprint and (
                    current_fingerprint != fingerprint or driver.current_url != previous_url
                ):
                    changed = True
                    break
            if not changed:
                break
        else:
            raise RuntimeError(
                f"pagination exceeded the safety limit of {max_pages} pages"
            )

        if not collected:
            raise RuntimeError("rendered pagination returned no public vacancy links")
        return list(collected.items())
    finally:
        driver.quit()
