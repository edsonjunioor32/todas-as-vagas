# -*- coding: utf-8 -*-
"""We Work Remotely — a large remote board. No JSON API, but a public RSS feed
per category. The main feed carries structured fields (category, region, type,
pubDate) and titles as "Company: Job Title". All-remote by definition.
"""
import time
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from ._common import strip_html, work_model_label, job

FEEDS = [
    "https://weworkremotely.com/remote-jobs.rss",                     # all categories, most recent
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://weworkremotely.com/categories/remote-sales-and-marketing-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    "https://weworkremotely.com/categories/remote-product-jobs.rss",
]
H = {"User-Agent": "Mozilla/5.0 (compatible; jobs-market-explorer/1.0)"}


def _rfc822(s):
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return ""


def fetch():
    seen, out = set(), []
    for url in FEEDS:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=25).read()
            items = ET.fromstring(raw).findall(".//item")
        except Exception as e:
            print(f"    [wwr] {url.split('/')[-1]}: {str(e)[:40]}")
            continue
        for it in items:
            link = (it.findtext("link") or "").strip()
            if not link or link in seen:
                continue
            seen.add(link)
            raw_title = (it.findtext("title") or "").strip()
            company, _, title = raw_title.partition(": ")
            if not title:
                company, title = "", raw_title
            region = (it.findtext("region") or "").strip()
            cat = (it.findtext("category") or "").strip()
            out.append(job("weworkremotely", link,
                title=title, company=company, url=link,
                work_model="remote",
                country=region or (it.findtext("country") or ""),
                market="Global remote",
                published_date=_rfc822(it.findtext("pubDate") or ""),
                description=strip_html(it.findtext("description") or ""),
                categories=[cat] if cat else []))
        time.sleep(0.3)
    return out
