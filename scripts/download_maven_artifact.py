#!/usr/bin/env python3
"""Download a pinned Maven artifact with retries for transient rate limits."""

import email.utils
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


MAX_ATTEMPTS = 6
CHUNK_SIZE = 1024 * 1024


def retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After")
    if retry_after:
        try:
            return min(max(float(retry_after), 1), 60)
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return min(max((retry_at - datetime.now(timezone.utc)).total_seconds(), 1), 60)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(2**attempt + random.random(), 60)


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "grocery-analytics-image-build"})
    temporary = destination.with_suffix(destination.suffix + ".part")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response, temporary.open("wb") as out:
                while chunk := response.read(CHUNK_SIZE):
                    out.write(chunk)
            os.replace(temporary, destination)
            print(f"Downloaded {url} to {destination}")
            return
        except urllib.error.HTTPError as error:
            temporary.unlink(missing_ok=True)
            if error.code != 429 and error.code < 500:
                raise
            if attempt == MAX_ATTEMPTS:
                raise
            delay = retry_delay(error, attempt)
            print(f"HTTP {error.code}; retrying in {delay:.1f}s ({attempt}/{MAX_ATTEMPTS})")
            time.sleep(delay)
        except urllib.error.URLError as error:
            temporary.unlink(missing_ok=True)
            if attempt == MAX_ATTEMPTS:
                raise
            delay = min(2**attempt + random.random(), 60)
            print(f"Download error {error}; retrying in {delay:.1f}s ({attempt}/{MAX_ATTEMPTS})")
            time.sleep(delay)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: download_maven_artifact.py URL DESTINATION")
    download(sys.argv[1], Path(sys.argv[2]))


if __name__ == "__main__":
    main()
