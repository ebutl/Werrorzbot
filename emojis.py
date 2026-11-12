import random


class PremiumEmoji:
    GRL = '<tg-emoji emoji-id="6138834878302524958">🥀</tg-emoji>'
    FAV = '<tg-emoji emoji-id="6230927657257668107">🥀</tg-emoji>'
    CALANDER = '<tg-emoji emoji-id="5274055917766202507">📅</tg-emoji>'
    COM = '<tg-emoji emoji-id="6154506501001057160">💻</tg-emoji>'
    SPEED = '<tg-emoji emoji-id="6044184811394831904">💻</tg-emoji>'
    USERS = '<tg-emoji emoji-id="5039789890133296083">🪽</tg-emoji>'
    FLY = '<tg-emoji emoji-id="6044262726396546853">🪽</tg-emoji>'
    FIRE = '<tg-emoji emoji-id="6044260346984665434">🔥</tg-emoji>'
    RIGHT = '<tg-emoji emoji-id="6043995137049104461">➡️</tg-emoji>'
    THUNDER = '<tg-emoji emoji-id="6044184811394831904">⚡</tg-emoji>'
    HOME = '<tg-emoji emoji-id="5978692057688968853">⚡</tg-emoji>'
    GG = '<tg-emoji emoji-id="5465465194056525619">👍</tg-emoji>'
    WHITE_F = '<tg-emoji emoji-id="5116414868357907335">🔥</tg-emoji>'
    DEAD = '<tg-emoji emoji-id="5978692057688968853">🚫</tg-emoji>'
    SEARCH = '<tg-emoji emoji-id="5893382531037794941">🚫</tg-emoji>'
    EMOJI_1 = '<tg-emoji emoji-id="5893382531037794941">⏳</tg-emoji>'
    EMOJI_2 = '<tg-emoji emoji-id="5256143829672672750">🤔</tg-emoji>'
    EMOJI_3 = '<tg-emoji emoji-id="5893365724830765382">🌞</tg-emoji>'
    EMOJI_4 = '<tg-emoji emoji-id="5895652322469482989">😆</tg-emoji>'
    EMOJI_5 = '<tg-emoji emoji-id="5893442248263078309">🥹</tg-emoji>'
    EMOJI_6 = '<tg-emoji emoji-id="5215327832040811010">🤣</tg-emoji>'
    EMOJI_7 = '<tg-emoji emoji-id="5197288647275071607">🦇</tg-emoji>'
    EMOJI_8 = '<tg-emoji emoji-id="5274055917766202507">🎂</tg-emoji>'
    CAR = '<tg-emoji emoji-id="6138413189823469510">🚗</tg-emoji>'
    WARNING = '<tg-emoji emoji-id="6044260346984665434">⚠️</tg-emoji>'
    INFO = '<tg-emoji emoji-id="6043995137049104461">ℹ️</tg-emoji>'
    KEY = '<tg-emoji emoji-id="6044184811394831904">🔑</tg-emoji>'
    REDEEM = '<tg-emoji emoji-id="6138834878302524958">♻️</tg-emoji>'
    PREMIUM = '<tg-emoji emoji-id="6138834878302524958">♻️</tg-emoji>'
    FREE = '<tg-emoji emoji-id="6138834878302524958">♻️</tg-emoji>'
    NOTE = '<tg-emoji emoji-id="5215209935188534658">📝</tg-emoji>'
    DECLINED = '<tg-emoji emoji-id="5042112436648281096">❌</tg-emoji>'
    APPROVED = '<tg-emoji emoji-id="5039793437776282663">✅</tg-emoji>'
    SUCCESS = '<tg-emoji emoji-id="5039844895779455925">✅</tg-emoji>'
    ERROR = '<tg-emoji emoji-id="5039665997506675838">⚠️</tg-emoji>'
    CARD = '<tg-emoji emoji-id="5800709991627232190">💳</tg-emoji>'
    RESPONSE = '<tg-emoji emoji-id="5039579582764680065">⚡</tg-emoji>'
    GATE = '<tg-emoji emoji-id="6044184811394831904">⚡</tg-emoji>'
    GATES = '<tg-emoji emoji-id="6044184811394831904">⚡</tg-emoji>'
    ELAPS = '<tg-emoji emoji-id="5902050947567194830">⌛</tg-emoji>'
    LOAD = '<tg-emoji emoji-id="6044134508737859533">🔌</tg-emoji>'
    PX = '<tg-emoji emoji-id="5447448489149625830">🔌</tg-emoji>'

    @classmethod
    def get_charge_emoji(cls):
        return '<tg-emoji emoji-id="5321125250342083365">💎</tg-emoji>'

    @property
    def CHARGE(self):
        return self.get_charge_emoji()

    AMOUNT = '<tg-emoji emoji-id="5042050649248760772">🥧</tg-emoji>'
    MONEY = '<tg-emoji emoji-id="5042050649248760772">💰</tg-emoji>'
    HIT = '<tg-emoji emoji-id="6044260346984665434">🔥</tg-emoji>'
    BACK = '<tg-emoji emoji-id="6046496457282819707">⬅️</tg-emoji>'
    CLOSE = '<tg-emoji emoji-id="6043931300950184015">❌</tg-emoji>'
    REFRESH = '<tg-emoji emoji-id="6044262726396546853">🔄</tg-emoji>'
    SHIELD = '<tg-emoji emoji-id="5197288647275071607">🛡️</tg-emoji>'
    BAN = '<tg-emoji emoji-id="5256143829672672750">🚫</tg-emoji>'
    STATS = '<tg-emoji emoji-id="5215327832040811010">📊</tg-emoji>'
    REPORT = '<tg-emoji emoji-id="5274055917766202507">📄</tg-emoji>'
    DATABASE = '<tg-emoji emoji-id="5978692057688968853">💾</tg-emoji>'
    SETTINGS = '<tg-emoji emoji-id="5893382531037794941">⚙️</tg-emoji>'
    HELP = '<tg-emoji emoji-id="5256143829672672750">❓</tg-emoji>'
    DEV = '<tg-emoji emoji-id="6154506501001057160">❓</tg-emoji>'
    CLOCK = '<tg-emoji emoji-id="5893102202817352158">🕐</tg-emoji>'
    CALENDAR = '<tg-emoji emoji-id="5893442248263078309">📅</tg-emoji>'
    FILE = '<tg-emoji emoji-id="5893255507380014983">📑</tg-emoji>'
    STAR = '<tg-emoji emoji-id="5895652322469482989">⭐</tg-emoji>'
    LOCK = '<tg-emoji emoji-id="6044184811394831904">🔐</tg-emoji>'
    BOX = '<tg-emoji emoji-id="6044262726396546853">📦</tg-emoji>'
    TOOLS = '<tg-emoji emoji-id="5893382531037794941">🔧</tg-emoji>'
    GLOBE = '<tg-emoji emoji-id="6043995137049104461">🌐</tg-emoji>'
    SITES = '<tg-emoji emoji-id="5893365724830765382">🌍</tg-emoji>'
    SPARKLE = '<tg-emoji emoji-id="5978692057688968853">✨</tg-emoji>'
    GEAR = '<tg-emoji emoji-id="5893382531037794941">⚙️</tg-emoji>'
    CROWN = '<tg-emoji emoji-id="5895652322469482989">👑</tg-emoji>'
    USER = '<tg-emoji emoji-id="5258274739041883702">👤</tg-emoji>'
    OWNER = '<tg-emoji emoji-id="5339300332168036242">👤</tg-emoji>'
    LINK = '<tg-emoji emoji-id="6044184811394831904">🔗</tg-emoji>'
    BITCOIN = '<tg-emoji emoji-id="5893442248263078309">₿</tg-emoji>'
    SOLANA = '<tg-emoji emoji-id="5197288647275071607">◎</tg-emoji>'
    BINANCE = '<tg-emoji emoji-id="5274055917766202507">🟡</tg-emoji>'
    TIP = '<tg-emoji emoji-id="5893290369629556374">💡</tg-emoji>'


class ButtonEmoji:
    PROFILE = "5978784790327856236"
    SEARCH = "5893382531037794941"
    CLOSE = "6043931300950184015"
    BACK = "6046496457282819707"
    GATES = "6044262726396546853"
    PRICING = "6044260346984665434"
    GROUP = "6043995137049104461"
    UPDATES = "6044184811394831904"
    DEV = "6138834878302524958"
    SUPPORT = "6230927657257668107"
    HOME = "5978692057688968853"
    SETTINGS_EMOJI = "5893382531037794941"
    HELP_EMOJI = "5256143829672672750"
    ADMIN = "5197288647275071607"
    USERS = "5893365724830765382"
    PREMIUM = "5895652322469482989"
    KEYS = "5893442248263078309"
    STATS_EMOJI = "5215327832040811010"
    REFRESH_EMOJI = "5274055917766202507"
    CLOSE_EMOJI = "6043931300950184015"
    BACK_EMOJI = "6046496457282819707"
    ADD = "5893382531037794941"
    DELETE = "5256143829672672750"
    VIEW = "5893365724830765382"
    GENERATE = "5895652322469482989"
    COPY = "5893442248263078309"
    REPORT = "5902016123972358349"
    BAN = "5256143829672672750"
    PROXIES = "6044184811394831904"
    SITES = "5893102202817352158"
    APPROVE = "5978692057688968853"
    APPROVED = "6043995137049104461"
    THUNDER = "6044184811394831904"
    DOWNLOAD = "6041705726206808304"
    FIRE = "6044260346984665434"
    REDEEM = "6138834878302524958"
    HIIT = "5339300332168036242"