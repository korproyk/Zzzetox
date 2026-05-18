"""
Nickname profanity / offensive-term filter (hate, sexual, vulgar, etc.).

FORBIDDEN_TERMS is passed to templates from Flask — extend terms here only.
"""

from __future__ import annotations

import re
import unicodedata

NICKNAME_REJECT_MESSAGE = "Please choose a different nickname."

# Letters-only substring (>= 6 letters) on the collapsed nickname — compounds / unambiguous slurs.
_FORBIDDEN_SUBSTR_LONG: tuple[str, ...] = (
    "nigger",
    "nigga",
    "niggaz",
    "faggot",
    "faggots",
    "cocksucker",
    "motherfucker",
    "clusterfuck",
    "dumbfuck",
    "childporn",
    "childporno",
    "rapeyou",
    "hitler",
    "genocide",
    "holocaust",
    "rule34",
    "blowjob",
    "handjob",
    "deepthroat",
    "creampie",
    "gangbang",
    "bukkake",
    "masturbate",
    "masturbation",
    "ejaculate",
    "ejaculation",
    "cunnilingus",
    "fellatio",
    "pedophilia",
    "pedophile",
    "necrophilia",
    "necrophile",
    "zoophilia",
    "zoophile",
    "incestuous",
    "molestation",
    "cockblock",
    "pornstar",
    "pornstars",
    "cumshot",
    "cumshots",
    "dickpics",
    "sexslave",
    "sexslaves",
    "rapeplay",
    "lolicon",
    "shotacon",
    "gooning",
    "goonette",
    "hentai",
    "ahegao",
    "bondage",
    "strangle",
    "lynching",
    "throatfuck",
    "titfuck",
    "skullfuck",
    "autofellatio",
    "futanari",
    "netorare",
)


def _nfkc_casefold(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").casefold()


def _letters_only(s: str) -> str:
    return "".join(ch for ch in _nfkc_casefold(s) if ch.isalpha())


def _flexible_subsequence_pattern(term: str) -> re.Pattern | None:
    """Letters of term in order; only non-word characters (and underscores) may appear between them."""
    letters = [c for c in _nfkc_casefold(term) if c.isalpha()]
    if len(letters) < 2:
        return None
    # Allow underscores between letters (e.g. f_u_c_k) but not skip real letters inside a word.
    gap = r"[\W_]*"
    parts = [re.escape(c) for c in letters]
    try:
        return re.compile(gap.join(parts), re.IGNORECASE | re.UNICODE)
    except re.error:
        return None


def _substring_long_hits(collapsed_nick: str) -> bool:
    low = collapsed_nick.casefold()
    for t in _FORBIDDEN_SUBSTR_LONG:
        tl = _letters_only(t).casefold()
        if len(tl) >= 6 and tl in low:
            return True
    return False


_COMPILED: list[tuple[str, re.Pattern]] = []

# Asterisk (or similar) used as a vowel mask — not matched by letter-only gaps.
_EXTRA_MASK_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"f[^\w]*\*[^\w]*c[^\w]*k", re.IGNORECASE | re.UNICODE),
    re.compile(r"s[^\w]*\*[^\w]*i[^\w]*t", re.IGNORECASE | re.UNICODE),
    re.compile(r"b[^\w]*\*[^\w]*t[^\w]*c[^\w]*h", re.IGNORECASE | re.UNICODE),
    re.compile(r"p[^\w]*\*[^\w]*r[^\w]*n", re.IGNORECASE | re.UNICODE),
    re.compile(r"n[^\w]*\*[^\w]*g[^\w]*g", re.IGNORECASE | re.UNICODE),
    re.compile(r"d[^\w]*\*[^\w]*i[^\w]*c[^\w]*k", re.IGNORECASE | re.UNICODE),
)


def _build_compiled(terms: tuple[str, ...]) -> None:
    global _COMPILED
    seen: set[str] = set()
    out: list[tuple[str, re.Pattern]] = []
    for raw in terms:
        key = _letters_only(raw).casefold()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        pat = _flexible_subsequence_pattern(raw)
        if pat:
            out.append((raw, pat))
    _COMPILED = out


FORBIDDEN_TERMS: tuple[str, ...] = (
    # General vulgar / insults
    "fuck",
    "fuk",
    "fvck",
    "feck",
    "fuxk",
    "shit",
    "shite",
    "bitch",
    "biatch",
    "bastard",
    "asshole",
    "arsehole",
    "dickhead",
    "diks",
    "pussy",
    "pusy",
    "twat",
    "prick",
    "wank",
    "wanker",
    "douche",
    "douchebag",
    "scumbag",
    "jackass",
    "dumbass",
    "dipshit",
    "shithead",
    "clusterfuck",
    "bullshit",
    "horseshit",
    "crap",
    "damn",
    "dammit",
    "piss",
    "pissed",
    "pissoff",
    "cunt",
    "ballsack",
    "nutsack",
    "jerkoff",
    "jizz",
    "horny",
    "thot",
    # Sexual / lewd (short tokens still use gap-regex; avoid ambiguous 3-letter-only where possible)
    "slut",
    "slutty",
    "whore",
    "whoring",
    "hooker",
    "escort",
    "stripper",
    "strippers",
    "nudes",
    "nudity",
    "naked",
    "nsfw",
    "lewd",
    "erotic",
    "orgasm",
    "climax",
    "fetish",
    "bdsm",
    "bondage",
    "dominatrix",
    "submissive",
    "milf",
    "dilf",
    "gilf",
    "twerk",
    "twerking",
    "dildo",
    "vibrator",
    "vibrators",
    "buttplug",
    "strap-on",
    "strapon",
    "blowjob",
    "handjob",
    "paizuri",
    "deepthroat",
    "creampie",
    "gangbang",
    "bukkake",
    "facesit",
    "facesitting",
    "rimjob",
    "felch",
    "watersports",
    "pegging",
    "gooning",
    "edging",
    "hentai",
    "ahegao",
    "rule34",
    "r34",
    "lolicon",
    "loli",
    "shota",
    "shotacon",
    "toddlercon",
    "pedophile",
    "pedophilia",
    "molest",
    "molester",
    "groomer",
    "grooming",
    "rapist",
    "raping",
    "raped",
    "necro",
    "zoophile",
    "bestial",
    "incest",
    "cumdump",
    "cumslut",
    "cockslut",
    "porn",
    "porno",
    "pornhub",
    "xvideos",
    "redtube",
    "xhamster",
    "sexting",
    "sexchat",
    "sexcam",
    "camgirl",
    "camboy",
    "camwhore",
    "suckme",
    "suckmy",
    "suckit",
    "blowme",
    "fuckme",
    "fuckyou",
    "fku",
    "pornstar",
    "pornstars",
    "xvids",
    "hardcore",
    "softcore",
    "xxx",
    "xxxxx",
    "upskirt",
    "downblouse",
    "cameltoe",
    "nipples",
    "nipple",
    "areola",
    "vagina",
    "penis",
    "phallus",
    "clitoris",
    "clit",
    "labia",
    "scrotum",
    "testicle",
    "testicles",
    "boner",
    "erection",
    "ejaculate",
    "masturbate",
    "masturbation",
    "fellatio",
    "sex",
    "sexy",
    "cunnilingus",
    "analingus",
    "sodomy",
    "sodomize",
    "sodomise",
    "prostitute",
    "brothel",
    "pimp",
    "pimping",
    "whored",
    "gangrape",
    "daterape",
    "childporn",
    "jailbait",
    "underage",
    "lolihentai",
    # Hate / slurs / violence
    "nazi",
    "nazis",
    "hitler",
    "heilhitler",
    "holocaust",
    "genocide",
    "nigger",
    "nigga",
    "niggas",
    "niglet",
    "niglets",
    "coon",
    "coons",
    "gook",
    "gooks",
    "chink",
    "chinks",
    "chingchong",
    "chingchangchong",
    "wetback",
    "wetbacks",
    "beaner",
    "beaners",
    "towelhead",
    "raghead",
    "sandnigger",
    "kike",
    "kyke",
    "faggot",
    "dyke",
    "dykes",
    "tranny",
    "trannies",
    "shemale",
    "retard",
    "retarded",
    "mongoloid",
    "cocksucker",
    "motherfucker",
    "dicksucker",
    "terrorist",
    "kkk",
    "lynch",
    "lynching",
    # Self-harm
    "kys",
    "kyz",
    "kill yourself",
    "go die",
    "suicide",
    "hang yourself",
    # Spanish / French / German / Portuguese / Italian
    "puta",
    "puto",
    "putas",
    "mierda",
    "joder",
    "cabrón",
    "cabron",
    "pendejo",
    "pendeja",
    "hijoputa",
    "hijaputa",
    "putain",
    "merde",
    "connard",
    "connasse",
    "enculé",
    "encule",
    "salope",
    "scheisse",
    "scheiße",
    "fick",
    "ficken",
    "hurensohn",
    "nutte",
    "fotze",
    "schwanz",
    "caralho",
    "vaffanculo",
    "stronzo",
    "merda",
    "cornuto",
    # Russian (Latin)
    "suka",
    "sukin",
    "blyat",
    "blyad",
    "pidor",
    "pidoras",
    "gandon",
    "hui",
    # Chinese (romanization common in nicknames)
    "shabi",
    "shabee",
    "caonima",
    "cao ni ma",
    "gan ni ma",
    "ganbi",
    "tmd",
    "nmsl",
    # More English sexual / crude (longer or distinctive)
    "phuk",
    "phuck",
    "fcuk",
    "stupid",
    "dumb",
    "idiot",
    "idiotic",
    "retarded",
    "retard",
    "moron",
    "moronic",
    "brainless",
    "brainless",
    "zit",
    "schlong",
    "smegma",
    "rimming",
    "anus",
    "rectum",
    "sodomite",
    "cuckold",
    "slutfest",
    "orgy",
    "orgies",
    "horndog",
    "hornbag",
    "throatpie",
    "throatfuck",
    "titfuck",
    "skullfuck",
    "ballsdeep",
    "bareback",
    "creampied",
    "gangbanged",
    "felching",
    "fisting",
    "fisted",
    "squirting",
    "prolapse",
    "rule63",
    "futanari",
    "netorare",
    "ahegaoface",
    "bondagesex",
    "domsub",
    "rapebait",
    "rapeme",
    # Turkish / Thai / Hindi romanization (common online)
    "siktir",
    "amcık",
    "kwai",
    "madarchod",
    "behenchod",
    "chutiya",
    "bhosdike",
    # Italian / Portuguese extra
    "puttana",
    "stronza",
    "cornuta",
    "filho da puta",
    "filhodaputa",
    "vai tomar no cu",
)


# Letters, digits, US-keyboard symbols — printable ASCII except space (no Korean / non-Latin scripts).
_NICKNAME_PRINTABLE_ASCII = re.compile(r"^[\x21-\x7E]{2,16}$")

NICKNAME_CHARSET_MESSAGE = (
    "Nickname must be 2–16 characters: English letters, numbers, or symbols "
    "(ASCII printable, no spaces; Korean and other non-ASCII characters are not allowed)."
)


def nickname_validation_error(name: str | None) -> str | None:
    if not isinstance(name, str):
        return NICKNAME_REJECT_MESSAGE
    s = name.strip()
    if not s:
        return None
    if not _NICKNAME_PRINTABLE_ASCII.fullmatch(s):
        return NICKNAME_CHARSET_MESSAGE
    collapsed = _letters_only(s)
    if _substring_long_hits(collapsed):
        return NICKNAME_REJECT_MESSAGE
    for _, pat in _COMPILED:
        if pat.search(s):
            return NICKNAME_REJECT_MESSAGE
    for pat in _EXTRA_MASK_PATTERNS:
        if pat.search(s):
            return NICKNAME_REJECT_MESSAGE
    return None


_build_compiled(FORBIDDEN_TERMS)
