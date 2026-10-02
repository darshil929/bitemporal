"""Requests to BSE's API host, which serves corporate actions and the list of scrips."""

# The venue's edge refuses a client that does not present a current browser's headers, an older
# browser version included, and the endpoint answers a request carrying no Origin or Referer with a
# page rather than JSON.
REQUIRED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/153.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Origin": "https://www.bseindia.com/",
    "Referer": "https://www.bseindia.com/",
    "Connection": "keep-alive",
    "Sec-Fetch-Site": "same-site",
}
