"""jio_core.py — External API Wrapper (Fixed for Integer Amounts)"""

import requests
import urllib3
from urllib.parse import quote
from typing import Optional, Tuple

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

JIO_API_URL = "https://doom1.up.railway.app/check"

def _mask(card_num: str) -> str: 
    return f"{card_num[:6]}xxxxxx{card_num[-4:]}"

def _format_proxy_for_api(proxy: str) -> str:
    raw = proxy.strip()
    if raw.startswith("http://"): raw = raw[len("http://"):]
    elif raw.startswith("https://"): raw = raw[len("https://"):]
    if "@" in raw:
        userinfo, hostport = raw.split("@", 1)
        user, _, pwd = userinfo.partition(":")
        host, _, port = hostport.rpartition(":")
        return f"{host}:{port}:{user}:{pwd}"
    return raw

def _resp(status: str, response: str, number: str, card: str, amount=None, gate: str = "jio") -> dict:
    return {
        "status": status.lower(), 
        "amount": amount if amount not in (None, "") else "N/A", 
        "gate": gate, 
        "response": response, 
        "number": number, 
        "card": card
    }

RESP_OK_KEYWORDS = ("approved", "success", "successful", "charged", "captured", "succeeded", "paid", "order_paid", "processed", "payment_success")
REAL_OK_KEYWORDS = ("payment successful", "payment succeeded", "payment completed", "approved", "successfully processed", "charged successfully", "order has been paid", "payment was successful", "processed successfully")
INSUFFICIENT_KEYWORDS = ("insufficient", "insufficient_funds", "not enough balance", "no enough balance", "low balance", "insufficient balance", "no balance", "unauthorized_transaction")
THREED_KEYWORDS = ("3ds", "3d secure", "3d_secure", "authentication", "auth_required", "require_action", "requires_action", "challenge", "captcha", "otp", "redirect", "verification required", "confirm the payment", "confirm your card", "card blocked from 3ds", "frictionless")
DECLINED_KEYWORDS = ("declined", "decline", "rejected", "do_not_honor", "do not honor", "not approved", "couldn't approve", "couldnt approve", "could not approve", "fraud", "expired", "invalid", "refused", "unable", "could not", "card_error", "generic_decline", "processing_error", "lost_card", "stolen_card", "call_issuer", "pickup_card", "not supported", "your card provider declined", "bank declined", "cannot be used", "not_subscribed", "bad_request", "runtimeerror", "initiate_recharge", "not available", "not found")

def _contains(text: str, keywords: Tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)

def _map_status(raw_response: str, real_response: str) -> Tuple[str, bool, str]:
    resp = (raw_response or "").lower()
    real = (real_response or "").lower()
    
    if _contains(resp, RESP_OK_KEYWORDS) or _contains(real, REAL_OK_KEYWORDS):
        return "charged", True, "Payment Successful."
    if _contains(resp, INSUFFICIENT_KEYWORDS) or _contains(real, INSUFFICIENT_KEYWORDS):
        return "approved", True, "Your card does not have enough balance."
    if _contains(resp, THREED_KEYWORDS) or _contains(real, THREED_KEYWORDS):
        return "approved", True, "3DS Required."
    if _contains(resp, DECLINED_KEYWORDS) or _contains(real, DECLINED_KEYWORDS):
        # Clean up the error message to look nice
        clean_resp = str(real_response or raw_response)
        if "not available" in clean_resp.lower(): 
            clean_resp = "Amount not available for this number."
        elif "not_subscribed" in clean_resp.lower():
            clean_resp = "Invalid Jio Number / Not Subscribed."
        return "declined", False, clean_resp
    return "declined", False, str(real_response or raw_response or "Unknown Response")

def run_jio(number: str, card: dict, amount: float, proxy: Optional[str] = None) -> dict:
    masked = _mask(card["cc"])
    gateway = "jio"
    
    # ═══ FIX: Send integer amount (19 instead of 19.0) ═══
    amount_str = str(int(amount)) if float(amount).is_integer() else str(amount)
    
    cc = f"{card['cc']}|{card['mm']}|{card['yy']}|{card['cvv']}"
    p_fmt = _format_proxy_for_api(proxy) if proxy else ""
    
    url = f"{JIO_API_URL}?cc={quote(cc)}&number={quote(number)}&proxy={quote(p_fmt)}&amount={quote(amount_str)}"
    
    try:
        resp = requests.get(url, timeout=90, verify=False)
        
        if resp.status_code == 400:
            return _resp("declined", "Invalid Jio Number / Not Subscribed", number, masked, amount=amount_str, gate=gateway)
            
        if resp.status_code != 200:
            return _resp("error", f"API HTTP {resp.status_code}", number, masked, amount=amount_str, gate=gateway)

        data = resp.json()
        raw_resp = str(data.get("response", "Unknown"))
        real_resp = str(data.get("real-response") or raw_resp)
        
        status, is_hit, display = _map_status(raw_resp, real_resp)
        
        bot_status = "error"
        if status == "charged": bot_status = "charged"
        elif status == "approved": bot_status = "approved"
        elif status == "declined": bot_status = "declined"
        
        return _resp(bot_status, display, number, masked, amount=amount_str, gate=gateway)
        
    except requests.exceptions.Timeout:
        return _resp("declined", "API Timeout", number, masked, amount=amount_str, gate=gateway)
    except Exception as e:
        return _resp("error", f"API Error: {str(e)[:40]}", number, masked, amount=amount_str, gate=gateway)
