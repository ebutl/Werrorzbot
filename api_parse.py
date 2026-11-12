"""api_parse.py — Parse API response fields consistently.
Handles:
  - 'Gateway' or 'Gate' keys
  - 'Price': '12.00' + 'Currency': 'USD'   (separate)
  - 'Price': '12.00 AUD'                    (embedded)
"""

PRICE_SYMBOLS = {
    "USD": "$", "GBP": "£", "EUR": "€", "INR": "₹",
    "AUD": "A$", "CAD": "C$", "JPY": "¥", "SGD": "S$",
    "CHF": "CHF", "DKK": "kr", "NZD": "NZ$",
}


def get_gateway(ar):
    """API may return 'Gateway' OR 'Gate' (or lowercase variants)."""
    if not ar:
        return "N/A"
    val = (ar.get("Gateway") or ar.get("Gate")
           or ar.get("gateway") or ar.get("gate") or "N/A")
    val = str(val).strip()
    return val if val else "N/A"


def get_price_currency(ar):
    """Return (price_float, currency_str, sym_str, display_str).
    Supports embedded currency: Price='12.00 AUD'
    or separate: Price='12.00' + Currency='USD'
    """
    price_raw = (ar.get("Price") if ar else None) \
                or (ar.get("price") if ar else None) or "0.00"
    currency_raw = (ar.get("Currency") if ar else None) \
                   or (ar.get("currency") if ar else None) or ""

    price_str = str(price_raw).strip()
    currency = str(currency_raw).strip().upper()

    parts = price_str.split()
    if len(parts) >= 2:
        try:
            price_val = float(parts[0].replace(",", ""))
        except ValueError:
            price_val = 0.0
        if not currency:
            currency = parts[1].upper()
    else:
        try:
            price_val = float(price_str.replace(",", "") or "0")
        except ValueError:
            price_val = 0.0

    if not currency:
        currency = "USD"

    sym = PRICE_SYMBOLS.get(currency, currency)
    display = f"{price_val:.2f} {currency}"
    return price_val, currency, sym, display


def get_price_display(ar):
    """Convenience — just the display string like '12.00 AUD'."""
    return get_price_currency(ar)[3]