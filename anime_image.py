import random
import logging
import aiohttp
from config import ANIME_FALLBACK

logger = logging.getLogger(__name__)

_APIS = [
    "https://api.waifu.pics/sfw/waifu",
    "https://api.waifu.pics/sfw/neko",
    "https://nekos.best/api/v2/neko",
]


async def get_anime_image() -> str:
    apis = _APIS.copy()
    random.shuffle(apis)
    for api in apis:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(api, timeout=aiohttp.ClientTimeout(total=6)) as r:
                    if r.status != 200:
                        continue
                    d = await r.json(content_type=None)
                    url = d.get("url")
                    if url and str(url).startswith("http"):
                        return url
                    res = d.get("results")
                    if res and isinstance(res, list):
                        url = res[0].get("url")
                        if url and str(url).startswith("http"):
                            return url
        except Exception:
            continue
    return ANIME_FALLBACK