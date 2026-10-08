"""Bounded, resumable company icon ingestion, independent of page requests.

Company website identity is read from PSX. Google supplies that site's favicon;
this is a website icon, not a verified corporate wordmark. Only small PNGs are
accepted. No arbitrary company website is fetched by the server.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import re
import struct
from urllib.parse import urlencode, urlparse, quote

from bs4 import BeautifulSoup
import httpx
from sqlalchemy import or_, select
from app.db.session import SessionLocal
from app.models.market import Company, CompanyMark


def profile_website(html):
    soup = BeautifulSoup(html, "html.parser")
    for heading in soup.select(".item__head"):
        if heading.get_text(strip=True).upper() != "WEBSITE":
            continue
        sibling = heading.find_next_sibling()
        link = sibling.find("a", href=True) if sibling else None
        url = link["href"].strip() if link else ""
        parsed = urlparse(url)
        if parsed.scheme in ("https", "http") and parsed.hostname and "." in parsed.hostname:
            return url
    return None


def valid_icon(content):
    if not 24 <= len(content) <= 131072 or content[:8] != b"\x89PNG\r\n\x1a\n" or content[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", content[16:24])
    # Google's missing-site globe is 16px. Never persist it as a company logo.
    return 16 < width <= 256 and 16 < height <= 256


def fetch_mark(symbol):
    profile_url = f"https://dps.psx.com.pk/company/{quote(symbol, safe='')}"
    result = {"symbol": symbol, "profile_source_url": profile_url, "status": "unavailable"}
    if not re.fullmatch(r"[A-Z0-9.-]{1,30}", symbol):
        return result
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            response = client.get(profile_url)
            response.raise_for_status()
            website = profile_website(response.text)
            result["website"] = website
            if not website:
                return result
            url = "https://www.google.com/s2/favicons?" + urlencode({"domain": urlparse(website).hostname, "sz": 64})
            result["image_source_url"] = url
            image = client.get(url)
            image.raise_for_status()
            if valid_icon(image.content):
                result.update(content=image.content, sha256=sha256(image.content).hexdigest(), status="available")
    except httpx.HTTPError:
        result["status"] = "failed"
    return result


def run_once(limit=1000):
    cutoff = datetime.now(UTC) - timedelta(days=30)
    with SessionLocal() as db:
        symbols = list(db.scalars(select(Company.symbol).outerjoin(CompanyMark, CompanyMark.symbol == Company.symbol)
            .where(Company.is_active.is_(True), or_(CompanyMark.symbol.is_(None), CompanyMark.checked_at < cutoff))
            .order_by(CompanyMark.checked_at.asc().nullsfirst(), Company.symbol).limit(limit)))
    counts = {"attempted": len(symbols), "available": 0, "unavailable": 0, "failed": 0}
    # Four external requests at most; DB writes remain serial and commit per company.
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(fetch_mark, symbols):
            with SessionLocal() as db:
                mark = db.get(CompanyMark, result["symbol"])
                if not mark:
                    mark = CompanyMark(symbol=result["symbol"], profile_source_url=result["profile_source_url"])
                    db.add(mark)
                mark.checked_at = datetime.now(UTC)
                # A transient source failure never destroys a previously stored icon.
                for key, value in result.items():
                    if key == "status" and mark.content and value != "available":
                        continue
                    setattr(mark, key, value)
                if result.get("website"):
                    company = db.scalar(select(Company).where(Company.symbol == result["symbol"]))
                    company.official_website = result["website"]
                db.commit()
            counts[result["status"]] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(run_once(max(1, min(args.limit, 1000)))))
