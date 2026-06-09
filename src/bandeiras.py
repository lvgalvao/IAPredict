"""Bandeiras (emoji) das seleções, para o dashboard.

Mapeia o nome da seleção (grafia do dataset, em inglês) para o emoji da bandeira. Países sem
mapeamento recebem 🏳️ como fallback. Inglaterra/Escócia/País de Gales usam os emojis de
subdivisão do Reino Unido (tag sequences).
"""

from __future__ import annotations

# Subdivisões do Reino Unido (não têm ISO-2 próprio para emoji regional).
_ESPECIAIS = {
    "England": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "Scotland": "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F",
    "Wales": "\U0001F3F4\U000E0067\U000E0062\U000E0077\U000E006C\U000E0073\U000E007F",
}

# Nome da seleção → código ISO-3166-1 alfa-2.
_ISO2 = {
    # 48 seleções da Copa 2026
    "Mexico": "MX", "South Africa": "ZA", "South Korea": "KR", "Czech Republic": "CZ",
    "Canada": "CA", "Bosnia and Herzegovina": "BA", "Qatar": "QA", "Switzerland": "CH",
    "Brazil": "BR", "Morocco": "MA", "Haiti": "HT", "United States": "US", "Paraguay": "PY",
    "Australia": "AU", "Turkey": "TR", "Germany": "DE", "Curaçao": "CW", "Ivory Coast": "CI",
    "Ecuador": "EC", "Netherlands": "NL", "Japan": "JP", "Sweden": "SE", "Tunisia": "TN",
    "Belgium": "BE", "Egypt": "EG", "Iran": "IR", "New Zealand": "NZ", "Spain": "ES",
    "Cape Verde": "CV", "Saudi Arabia": "SA", "Uruguay": "UY", "France": "FR", "Senegal": "SN",
    "Iraq": "IQ", "Norway": "NO", "Argentina": "AR", "Algeria": "DZ", "Austria": "AT",
    "Jordan": "JO", "Portugal": "PT", "DR Congo": "CD", "Uzbekistan": "UZ", "Colombia": "CO",
    "Croatia": "HR", "Ghana": "GH", "Panama": "PA",
    # Outras seleções frequentes (explorador de partidas)
    "Italy": "IT", "Poland": "PL", "Denmark": "DK", "Serbia": "RS", "Ukraine": "UA",
    "Russia": "RU", "Greece": "GR", "Hungary": "HU", "Romania": "RO", "Nigeria": "NG",
    "Cameroon": "CM", "Mali": "ML", "Burkina Faso": "BF", "Chile": "CL", "Peru": "PE",
    "Venezuela": "VE", "Bolivia": "BO", "Costa Rica": "CR", "Honduras": "HN", "Jamaica": "JM",
    "China": "CN", "China PR": "CN", "India": "IN", "Thailand": "TH", "Vietnam": "VN",
    "Indonesia": "ID", "Malaysia": "MY", "Philippines": "PH", "United Arab Emirates": "AE",
    "Oman": "OM", "Kuwait": "KW", "Bahrain": "BH", "Israel": "IL", "Republic of Ireland": "IE",
    "Northern Ireland": "GB", "Iceland": "IS", "Finland": "FI", "Slovakia": "SK",
    "Slovenia": "SI", "Bulgaria": "BG", "North Macedonia": "MK", "Albania": "AL",
    "Montenegro": "ME", "Kosovo": "XK", "Georgia": "GE", "Armenia": "AM", "Azerbaijan": "AZ",
    "Kazakhstan": "KZ", "Angola": "AO", "Zambia": "ZM", "Zimbabwe": "ZW", "Kenya": "KE",
    "Uganda": "UG", "Tanzania": "TZ", "Sudan": "SD", "Libya": "LY", "Guinea": "GN",
    "Gabon": "GA", "Benin": "BJ", "Togo": "TG", "Mozambique": "MZ", "Madagascar": "MG",
    "Mauritania": "MR", "Namibia": "NA", "Botswana": "BW", "Comoros": "KM", "Gambia": "GM",
    "Sierra Leone": "SL", "Liberia": "LR", "Niger": "NE", "Central African Republic": "CF",
    "Congo": "CG", "Equatorial Guinea": "GQ", "Ethiopia": "ET", "Rwanda": "RW", "Burundi": "BI",
    "Malawi": "MW", "Eswatini": "SZ", "Lesotho": "LS", "North Korea": "KP", "Syria": "SY",
    "Lebanon": "LB", "Palestine": "PS", "Yemen": "YE", "Tajikistan": "TJ", "Kyrgyzstan": "KG",
    "Turkmenistan": "TM", "Afghanistan": "AF", "Pakistan": "PK", "Bangladesh": "BD",
    "Sri Lanka": "LK", "Myanmar": "MM", "Cambodia": "KH", "Singapore": "SG", "Hong Kong": "HK",
    "Guatemala": "GT", "El Salvador": "SV", "Nicaragua": "NI", "Trinidad and Tobago": "TT",
    "Cuba": "CU", "Dominican Republic": "DO", "Suriname": "SR", "Guyana": "GY", "Bermuda": "BM",
}

FALLBACK = "🏳️"


def _emoji(iso2: str) -> str:
    """Converte um código ISO-2 no emoji de bandeira (regional indicators)."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


def bandeira(nome: str) -> str:
    """Emoji da bandeira da seleção (🏳️ se desconhecida)."""
    if nome in _ESPECIAIS:
        return _ESPECIAIS[nome]
    iso = _ISO2.get(nome)
    return _emoji(iso) if iso else FALLBACK


def com_bandeira(nome: str) -> str:
    """Nome precedido da bandeira, ex.: '🇧🇷 Brazil'."""
    return f"{bandeira(nome)} {nome}"
