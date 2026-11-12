import sys
from database import get_active_proxy_strings, create_connection_pool, setup_database
from jio_core import run_jio
from config import OWNER_ID
import asyncio

def test():
    create_connection_pool()
    setup_database()
    proxies = get_active_proxy_strings(OWNER_ID)
    if not proxies:
        print("❌ No proxies found in DB.")
        return
        
    print(f"🔍 Testing {len(proxies)} proxies against Jio...\n")
    card = {"cc": "4111111111111111", "mm": "12", "yy": "2025", "cvv": "123"}
    
    working = []
    for p in proxies:
        # Test with a random valid looking number
        res = run_jio("9999999999", card, 29, p)
        resp = res.get("response", "")
        if "Dead Proxy" not in resp and "CONNECT tunnel failed" not in resp and "curl: (7)" not in resp:
            print(f"✅ WORKING: {p} -> {resp}")
            working.append(p)
        else:
            print(f"❌ DEAD: {p}")
            
    print(f"\n🎯 Total Working: {len(working)} / {len(proxies)}")

if __name__ == "__main__":
    test()
