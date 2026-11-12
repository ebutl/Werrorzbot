"""ui.py — Button factory with colors + icons (works on any PTB 20+)"""

from telegram import InlineKeyboardButton as _IKB

try:
    from button_style import ButtonStyle
except ImportError:
    ButtonStyle = None

# ── Detect native support ──
_HAS_STYLE = False
_HAS_ICON = False
_HAS_API_KWARGS = False

try:
    _t = _IKB(text="x", callback_data="y", style="primary")
    _HAS_STYLE = True
    del _t
except Exception:
    pass

try:
    _t = _IKB(text="x", callback_data="y", icon_custom_emoji_id="5368324170671202286")
    _HAS_ICON = True
    del _t
except Exception:
    pass

try:
    _t = _IKB(text="x", callback_data="y", api_kwargs={"style": "primary"})
    _HAS_API_KWARGS = True
    del _t
except Exception:
    pass

print(f"[ui] native_style={_HAS_STYLE} native_icon={_HAS_ICON} api_kwargs={_HAS_API_KWARGS}")


def make_btn(text, callback_data=None, url=None, style=None, icon=None):
    """
    Build InlineKeyboardButton with optional style + icon.
    Tries native kwargs first, then api_kwargs, then plain.
    """
    kwargs = {"text": text}
    if callback_data is not None:
        kwargs["callback_data"] = callback_data
    if url is not None:
        kwargs["url"] = url

    sv = None
    if style is not None:
        sv = style.value if hasattr(style, "value") else str(style)

    # Path 1: native kwargs (PTB with Bot API 9.0 support)
    if sv and _HAS_STYLE:
        try:
            if icon and _HAS_ICON:
                return _IKB(**kwargs, style=sv, icon_custom_emoji_id=icon)
            return _IKB(**kwargs, style=sv)
        except Exception:
            pass

    # Path 2: api_kwargs (PTB 20+ supports this pass-through)
    api_kw = {}
    if sv:
        api_kw["style"] = sv
    if icon:
        api_kw["icon_custom_emoji_id"] = icon

    if api_kw:
        try:
            return _IKB(**kwargs, api_kwargs=api_kw)
        except Exception:
            pass

    # Path 3: plain (fallback)
    return _IKB(**kwargs)


def primary(text, cb=None, url=None, icon=None):
    return make_btn(text, cb, url, "primary", icon)


def success(text, cb=None, url=None, icon=None):
    return make_btn(text, cb, url, "success", icon)


def danger(text, cb=None, url=None, icon=None):
    return make_btn(text, cb, url, "danger", icon)