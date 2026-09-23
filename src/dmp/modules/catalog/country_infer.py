"""Infer a university's ISO-3166 alpha-2 country from free-form dump fields.

The university_data dump carries geography inconsistently: sometimes an
explicit ``university_identity.country.<source>``, more often only inside an
address/location string ("Shanghai, China", "Moscow, Russian Federation",
"Montreal CA H3T 1J4", "Dhaka, BD"). The dump importer uses
:func:`infer_country_code` to derive ``country_name`` payloads so fresh-PC
imports fill ``universities.country_id`` without manual SQL.

Rules (first hit wins), tuned against the full 2,885-row dump where they
resolved 1,941 of 1,943 country-less rows:
  1. standalone ISO segment          "Dhaka, BD"
  2. exact country/alias in a comma segment or whole string (trailing
     digits stripped)                 "Tétouan, Morocco 93000"
  3. US 5-digit ZIP                  "Rochester, MI 48309" → US
  4. ISO code + postal token         "Montreal CA H3T 1J4" → CA,
     (US-state∩ISO codes resolve to the  "Moscow RU 119571"  → RU
      country unless a US ZIP follows)
  5. standalone uppercase code token "Chicago US 60614"
  6. pure US-state segment           "Pittsburgh, PA" → US
  7. trailing word suffix            "Paris France", "Shaanxi China"
  8. city / region words             "Suceava", "Kuala Lumpur", "Gansu"
"""

from __future__ import annotations

import re
import unicodedata

ISO_CODE_BY_NAME = {
    'Andorra': 'AD',
    'United Arab Emirates': 'AE',
    'Afghanistan': 'AF',
    'Antigua and Barbuda': 'AG',
    'Albania': 'AL',
    'Armenia': 'AM',
    'Angola': 'AO',
    'Argentina': 'AR',
    'Austria': 'AT',
    'Australia': 'AU',
    'Azerbaijan': 'AZ',
    'Bosnia and Herzegovina': 'BA',
    'Barbados': 'BB',
    'Bangladesh': 'BD',
    'Belgium': 'BE',
    'Burkina Faso': 'BF',
    'Bulgaria': 'BG',
    'Bahrain': 'BH',
    'Burundi': 'BI',
    'Benin': 'BJ',
    'Brunei': 'BN',
    'Bolivia': 'BO',
    'Brazil': 'BR',
    'Bahamas': 'BS',
    'Bhutan': 'BT',
    'Botswana': 'BW',
    'Belarus': 'BY',
    'Belize': 'BZ',
    'Canada': 'CA',
    'Congo (DRC)': 'CD',
    'Central African Republic': 'CF',
    'Congo': 'CG',
    'Switzerland': 'CH',
    "Côte d'Ivoire": 'CI',
    'Chile': 'CL',
    'Cameroon': 'CM',
    'China': 'CN',
    'Colombia': 'CO',
    'Costa Rica': 'CR',
    'Cuba': 'CU',
    'Cabo Verde': 'CV',
    'Cyprus': 'CY',
    'Czechia': 'CZ',
    'Germany': 'DE',
    'Djibouti': 'DJ',
    'Denmark': 'DK',
    'Dominica': 'DM',
    'Dominican Republic': 'DO',
    'Algeria': 'DZ',
    'Ecuador': 'EC',
    'Estonia': 'EE',
    'Egypt': 'EG',
    'Eritrea': 'ER',
    'Spain': 'ES',
    'Ethiopia': 'ET',
    'Finland': 'FI',
    'Fiji': 'FJ',
    'Micronesia': 'FM',
    'France': 'FR',
    'Gabon': 'GA',
    'United Kingdom': 'GB',
    'Grenada': 'GD',
    'Georgia': 'GE',
    'Ghana': 'GH',
    'Gambia': 'GM',
    'Guinea': 'GN',
    'Equatorial Guinea': 'GQ',
    'Greece': 'GR',
    'Guatemala': 'GT',
    'Guinea-Bissau': 'GW',
    'Guyana': 'GY',
    'Honduras': 'HN',
    'Croatia': 'HR',
    'Haiti': 'HT',
    'Hungary': 'HU',
    'Indonesia': 'ID',
    'Ireland': 'IE',
    'Israel': 'IL',
    'India': 'IN',
    'Iraq': 'IQ',
    'Iran': 'IR',
    'Iceland': 'IS',
    'Italy': 'IT',
    'Jamaica': 'JM',
    'Jordan': 'JO',
    'Japan': 'JP',
    'Kenya': 'KE',
    'Kyrgyzstan': 'KG',
    'Cambodia': 'KH',
    'Kiribati': 'KI',
    'Comoros': 'KM',
    'Saint Kitts and Nevis': 'KN',
    'North Korea': 'KP',
    'South Korea': 'KR',
    'Kuwait': 'KW',
    'Kazakhstan': 'KZ',
    'Laos': 'LA',
    'Lebanon': 'LB',
    'Saint Lucia': 'LC',
    'Liechtenstein': 'LI',
    'Sri Lanka': 'LK',
    'Liberia': 'LR',
    'Lesotho': 'LS',
    'Lithuania': 'LT',
    'Luxembourg': 'LU',
    'Latvia': 'LV',
    'Libya': 'LY',
    'Morocco': 'MA',
    'Monaco': 'MC',
    'Moldova': 'MD',
    'Montenegro': 'ME',
    'Madagascar': 'MG',
    'Marshall Islands': 'MH',
    'North Macedonia': 'MK',
    'Mali': 'ML',
    'Myanmar': 'MM',
    'Mongolia': 'MN',
    'Mauritania': 'MR',
    'Malta': 'MT',
    'Mauritius': 'MU',
    'Maldives': 'MV',
    'Malawi': 'MW',
    'Mexico': 'MX',
    'Malaysia': 'MY',
    'Mozambique': 'MZ',
    'Namibia': 'NA',
    'Niger': 'NE',
    'Nigeria': 'NG',
    'Nicaragua': 'NI',
    'Netherlands': 'NL',
    'Norway': 'NO',
    'Nepal': 'NP',
    'Nauru': 'NR',
    'New Zealand': 'NZ',
    'Oman': 'OM',
    'Panama': 'PA',
    'Peru': 'PE',
    'Papua New Guinea': 'PG',
    'Philippines': 'PH',
    'Pakistan': 'PK',
    'Poland': 'PL',
    'Portugal': 'PT',
    'Palau': 'PW',
    'Paraguay': 'PY',
    'Qatar': 'QA',
    'Romania': 'RO',
    'Serbia': 'RS',
    'Russia': 'RU',
    'Rwanda': 'RW',
    'Saudi Arabia': 'SA',
    'Solomon Islands': 'SB',
    'Seychelles': 'SC',
    'Sudan': 'SD',
    'Sweden': 'SE',
    'Singapore': 'SG',
    'Slovenia': 'SI',
    'Slovakia': 'SK',
    'Sierra Leone': 'SL',
    'San Marino': 'SM',
    'Senegal': 'SN',
    'Somalia': 'SO',
    'Suriname': 'SR',
    'South Sudan': 'SS',
    'Sao Tome and Principe': 'ST',
    'El Salvador': 'SV',
    'Syria': 'SY',
    'Eswatini': 'SZ',
    'Chad': 'TD',
    'Togo': 'TG',
    'Thailand': 'TH',
    'Tajikistan': 'TJ',
    'Timor-Leste': 'TL',
    'Turkmenistan': 'TM',
    'Tunisia': 'TN',
    'Tonga': 'TO',
    'Turkey': 'TR',
    'Trinidad and Tobago': 'TT',
    'Tuvalu': 'TV',
    'Taiwan': 'TW',
    'Tanzania': 'TZ',
    'Ukraine': 'UA',
    'Uganda': 'UG',
    'United States': 'US',
    'Uruguay': 'UY',
    'Uzbekistan': 'UZ',
    'Vatican City': 'VA',
    'Saint Vincent and the Grenadines': 'VC',
    'Venezuela': 'VE',
    'Vietnam': 'VN',
    'Vanuatu': 'VU',
    'Samoa': 'WS',
    'Yemen': 'YE',
    'South Africa': 'ZA',
    'Zambia': 'ZM',
    'Zimbabwe': 'ZW',
}

# Alternative spellings / long ISO forms seen in QS/USNews/Shanghai data.
ALIASES: dict[str, str] = {
    "united states": "US", "united states of america": "US", "usa": "US",
    "u.s.": "US", "u.s.a.": "US", "america": "US", "puerto rico": "US",
    "united kingdom": "GB", "uk": "GB", "u.k.": "GB", "great britain": "GB",
    "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "russian federation": "RU", "russia": "RU",
    "turkiye": "TR", "türkiye": "TR", "turkey": "TR",
    "south korea": "KR", "korea, republic of": "KR", "republic of korea": "KR",
    "korea": "KR", "s. korea": "KR",
    "north korea": "KP", "korea, democratic people's republic of": "KP",
    # HK/MO are not separate rows in the seeded 195-country table → SAR → CN
    "hong kong sar": "CN", "hong kong sar china": "CN", "hong kong": "CN", "hk": "CN",
    "macao": "CN", "macau": "CN", "macao sar": "CN",
    "united arab emirates": "AE", "uae": "AE",
    "czech republic": "CZ", "czechia": "CZ",
    "viet nam": "VN", "vietnam": "VN",
    "iran, islamic republic of": "IR", "iran, islamic rep. of": "IR",
    "iran": "IR", "islamic republic of iran": "IR",
    "the netherlands": "NL", "netherlands": "NL", "holland": "NL",
    "syrian arab republic": "SY", "syria": "SY",
    "tanzania, united republic of": "TZ", "tanzania": "TZ",
    "bolivia, plurinational state of": "BO", "bolivia": "BO",
    "venezuela, bolivarian republic of": "VE", "venezuela": "VE",
    "taiwan": "TW", "taiwan, china": "TW", "chinese taipei": "TW",
    "moldova, republic of": "MD", "moldova": "MD",
    "brunei darussalam": "BN", "brunei": "BN",
    "lao people's democratic republic": "LA", "laos": "LA",
    "kyrgyz republic": "KG", "kyrgyzstan": "KG",
    "palestine, state of": "PS", "palestine": "PS",
    "congo, democratic republic of the": "CD", "democratic republic of the congo": "CD",
    "dr congo": "CD", "congo, republic of the": "CG", "republic of the congo": "CG",
    "cote d'ivoire": "CI", "côte d'ivoire": "CI", "ivory coast": "CI",
    "kosovo": "RS", "republic of kosovo": "RS",
}

# City-level rescues for dump rows whose address never names the country.
CITY: dict[str, str] = {
    "beirut": "LB", "dubai": "AE", "muscat": "OM", "kuala lumpur": "MY",
    "bachok": "MY", "santo domingo": "DO", "suceava": "RO", "ilheus": "BR",
    "vicosa": "BR", "canterbury": "GB", "southampton": "GB", "pontypridd": "GB",
    "treforest": "GB", "passau": "DE", "liege": "BE", "samarkand": "UZ",
    "tashkent": "UZ", "sumgait": "UZ", "caracas": "VE", "panama city": "PA",
    "bogota": "CO", "medellin": "CO", "kolkata": "IN", "sao paulo": "BR",
    "acton": "AU", "new delhi": "IN", "delhi": "IN", "sakaka": "SA",
    "nsukka": "NG", "enugu": "NG", "tunis": "TN", "madrid": "ES",
    "istanbul": "TR", "baton rouge": "US", "columbia": "US", "texcoco": "MX",
    "chapingo": "MX", "kufa": "IQ", "belgrano": "AR", "mendoza": "AR",
    "asuncion": "PY", "dublin": "IE", "moncloa": "ES", "munich": "DE",
    "baku": "AZ", "montreal": "CA", "quebec": "CA", "sherbrooke": "CA",
    "yogyakarta": "ID", "padang": "ID", "jakarta": "ID", "pelotas": "BR",
    "montpellier": "FR", "buenos aires": "AR", "rosario": "AR", "tandil": "AR",
    "capital federal": "AR", "lowell": "US", "munchen": "DE", "sogutozu": "TR",
    "coimbatore": "IN", "bandung": "ID", "knoxville": "US",
}

# Provinces / states / country words that appear in addresses or names.
REGION: dict[str, str] = {
    "arizona": "US", "louisiana": "US", "south carolina": "US", "oman": "OM",
    "dhofar": "OM", "north sumatra": "ID", "sumatra": "ID",
    "gansu": "CN", "shaanxi": "CN", "guizhou": "CN", "gan su sheng": "CN",
    "zunyi": "CN", "changzhi": "CN", "uttar pradesh": "IN",
    "azerbaijan": "AZ", "uzbekistan": "UZ", "nigeria": "NG", "venezuela": "VE",
    "kyrgyz": "KG", "idaho": "US", "tennessee": "US",
}

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

_ISO_RE = re.compile(r"^[A-Z]{2}$")
_ZIP5_RE = re.compile(r"\b([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
_POSTAL_RE = re.compile(r"\b([A-Z]{2})\s*[A-Z0-9]{2,8}\b")
_TOKEN_RE = re.compile(r"\b([A-Z]{2})\b")
_TRAILING_DIGITS_RE = re.compile(r"\s*\d[\d.\-/]*\s*$")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


_CODE_BY_ID: dict[str, str] = {}
_CODE_BY_NORM_NAME: dict[str, str] = {}


def _build_lookups() -> None:
    for name, code in ISO_CODE_BY_NAME.items():
        _CODE_BY_ID.setdefault(code, code)
        _CODE_BY_NORM_NAME[_norm(name)] = code
    for alias, code in ALIASES.items():
        if code in _CODE_BY_ID or code in ISO_CODE_BY_NAME.values():
            _CODE_BY_NORM_NAME.setdefault(_norm(alias), code)
    global _CITY_NORM, _REGION_NORM
    valid = set(ISO_CODE_BY_NAME.values())
    _CITY_NORM = {_norm(k): v for k, v in CITY.items() if v in valid}
    _REGION_NORM = {_norm(k): v for k, v in REGION.items() if v in valid}


def _valid(code: str) -> bool:
    return code in ISO_CODE_BY_NAME.values()


def _match_one(text: str) -> str | None:
    t = text.strip()
    if not t:
        return None
    segments = [s.strip() for s in t.split(",")]
    stripped = [s for s in (_TRAILING_DIGITS_RE.sub("", seg).strip() for seg in segments) if s]

    # 1) standalone ISO segment
    for seg in reversed(segments):
        if _ISO_RE.match(seg) and _valid(seg) and seg not in US_STATES:
            return seg
    # 2) exact country/alias on whole string or segments
    n_whole = _norm(t)
    if n_whole in _CODE_BY_NORM_NAME:
        return _CODE_BY_NORM_NAME[n_whole]
    for segs in (segments, stripped):
        for seg in reversed(segs):
            n = _norm(seg)
            if n in _CODE_BY_NORM_NAME:
                return _CODE_BY_NORM_NAME[n]
    # 3) US 5-digit ZIP
    if _ZIP5_RE.search(t):
        return "US"
    # 4) ISO code + postal token (US-state∩ISO → country unless US ZIP)
    for code in _POSTAL_RE.findall(t):
        if code == "PR":
            return "US"
        if _valid(code):
            if code not in US_STATES:
                return code
            if not re.search(r"\b" + code + r"\s+\d{5}(?:-\d{4})?\b", t):
                return code
    # 5) standalone uppercase code token
    for code in _TOKEN_RE.findall(t):
        if code == "PR":
            return "US"
        if _valid(code) and code not in US_STATES:
            return code
    # 6) pure US-state segment
    for seg in reversed(segments):
        if _ISO_RE.match(seg) and seg in US_STATES and not _valid(seg):
            return "US"
    # 7) trailing word suffixes
    words = n_whole.split()
    for take in (3, 2, 1):
        if len(words) >= take:
            suffix = " ".join(words[-take:])
            if suffix in _CODE_BY_NORM_NAME:
                return _CODE_BY_NORM_NAME[suffix]
    # 8) city / region words
    for seg in reversed(stripped or segments):
        n = _norm(seg)
        if n in _CITY_NORM:
            return _CITY_NORM[n]
        ws = n.split()
        for i in range(len(ws)):
            for take in (2, 1):
                if i + take <= len(ws):
                    w = " ".join(ws[i:i + take])
                    if w in _CITY_NORM:
                        return _CITY_NORM[w]
    ws = n_whole.split()
    for i in range(len(ws)):
        for take in (2, 1):
            if i + take <= len(ws):
                w = " ".join(ws[i:i + take])
                if w in _REGION_NORM:
                    return _REGION_NORM[w]
    return None


def infer_country_code(*texts: str | None) -> str | None:
    """First ISO alpha-2 derivable from the given address/location strings."""
    for text in texts:
        if not text or not text.strip():
            continue
        code = _match_one(text)
        if code:
            return code
    return None


_build_lookups()
