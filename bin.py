import asyncio
import aiohttp
import logging

logger = logging.getLogger(__name__)

BINLIST_URL = "https://bins.antipublic.cc/bins/{}"

async def get_bin_info(bin_number: str) -> dict:
    if not bin_number.isdigit() or len(bin_number) < 6:
        return {"error": "Invalid BIN"}
    
    async def _fetch():
        timeout = aiohttp.ClientTimeout(total=10.0, connect=10.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(BINLIST_URL.format(bin_number)) as resp:
                if resp.status == 429: return {"error": "Rate limit"}
                if resp.status == 404: return {"error": "Not found"}
                if resp.status != 200: return {"error": f"HTTP {resp.status}"}
                data = await resp.json()
                return {
                    "bin": data.get("bin"),
                    "scheme": data.get("brand"),
                    "type": data.get("type"),
                    "brand": data.get("level"),
                    "bank": data.get("bank"),
                    "country": data.get("country_name"),
                    "country_emoji": data.get("country_flag"),
                }
    
    try:
        return await asyncio.wait_for(_fetch(), timeout=12.0)
    except asyncio.TimeoutError:
        return {"error": "BIN API Timeout"}
    except Exception as e:
        return {"error": str(e)}