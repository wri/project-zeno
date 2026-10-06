"""Translation tables from MyGFW profile values to GNW profile codes.

MyGFW keeps its profile on the Resource Watch user object under
``applicationData.gfw``, written by the gfw repo's
``components/forms/profile``. These tables translate what that form stores
into the codes of the sibling config modules (``SECTORS``, ``SECTOR_ROLES``,
``TOPICS``, ``COUNTRIES``), which stay the single source of truth for codes.

Keys are the strings GFW shows or stores. The prefill mapper
(``src/api/services/profile_prefill.py``) folds case, spaces, slashes and
underscores before looking a value up, so one key matches the label, the
slug GFW saves (``"Forest_Management_Park_Management"``) and its lower-cased
form. A value missing from a table is left out of the suggestion.
"""

# gfw components/forms/profile/config.js, profileSectors[].value. GFW stores
# the value, which reads like a label. Anything starting with "Other" maps to
# "other" in the mapper, so "Other" is not listed here.
GFW_SECTORS = {
    "Government": "government",
    "Donor Institution / Agency": "donor",
    "Local NGO (national or subnational)": "local_ngo",
    "International NGO": "international_ngo",
    "UN or International Organization": "un_international",
    "Academic / Research Organization": "academic",
    "Journalist / Media Organization": "journalist",
    "Indigenous or Community-Based Organization": "indigenous",
    "Private sector": "private_sector",
    "Individual / No Affiliation": "individual",
}

# Role labels from GFW's pre-2025 per-sector role lists (the `sectors` object
# in components/forms/profile/config.js before gfw commit 722e3ae6e8). The
# current GFW form no longer saves a subsector, so only older profiles carry
# one. The same label means the same role in every sector, so the table is
# flat; the mapper then drops a role that is not offered for the mapped
# sector. "Other: <text>" maps to "other" in the mapper. Legacy roles with no
# GNW equivalent (Park/Forest Ranger, Supply Chain Analyst, Procurement
# Staff, Retailer/Trader, Land or Concession Owner) are deliberately absent.
GFW_SUBSECTORS = {
    "Forest Management/Park Management": "forest_management",
    "Law Enforcement": "law_enforcement",
    "Legislature/Parliament": "legislature",
    "Ministry/National Agency": "ministry_agency",
    "Subnational Agency": "subnational_agency",
    "Director/Executive": "director_executive",
    "Project/Program Manager": "project_manager",
    "Researcher": "researcher",
    "Monitoring/Evaluation": "monitoring_evaluation",
    "Monitoring/Evaluation Specialist": "monitoring_evaluation",
    "GIS/Technical Specialist": "gis_technical",
    "Field/Country Staff": "field_staff",
    "Field Staff": "field_staff",
    "Communications Specialist": "communications",
    "Faculty (Primary/Secondary)": "faculty_primary",
    "Faculty (University)": "faculty_university",
    "Student (Primary/Secondary)": "student_primary",
    "Student (University/Graduate)": "student_university",
    "Researcher (Post-Doc, Fellow, etc.)": "researcher_postdoc",
    "Reporter": "reporter",
    "Editor": "editor",
    "Community Leader": "community_leader",
    "Forest Manager/Monitor": "forest_manager",
    "Supply Chain Manager": "supply_chain_manager",
}

# GFW interests (current labels, their pre-2025 wording) and the legacy
# newsletter `topics`, mapped only where the GNW topic is an obvious match.
# The other GFW interests (fires, climate, monitoring, grants, ...) have no
# GNW topic and are deliberately absent.
GFW_INTERESTS = {
    "Deforestation": "combating_deforestation",
    "Deforestation/Forest Degradation": "combating_deforestation",
    "Landscape Restoration": "restoring_degraded_landscapes",
    "Reforestation/Landscape restoration": "restoring_degraded_landscapes",
    "Agricultural Supply Chains": "responsible_supply_chains",
    "Biodiversity": "protecting_ecosystems",
}

# GFW stores the country as a GADM 4.1 ISO3 code; GNW COUNTRIES is keyed by
# ISO 3166-1 alpha-2. Generated once from ISO 3166-1 (pycountry) rather than
# adding a dependency, plus GADM's own code for Kosovo. GADM's other non-ISO
# codes (XAD, XCA, XCL, XPI, XSP, ZNC, Z01-Z09) are deliberately absent.
GADM_ISO3_TO_COUNTRY_CODE = {
    "ABW": "AW",  # Aruba
    "AFG": "AF",  # Afghanistan
    "AGO": "AO",  # Angola
    "AIA": "AI",  # Anguilla
    "ALA": "AX",  # Åland Islands
    "ALB": "AL",  # Albania
    "AND": "AD",  # Andorra
    "ARE": "AE",  # United Arab Emirates
    "ARG": "AR",  # Argentina
    "ARM": "AM",  # Armenia
    "ASM": "AS",  # American Samoa
    "ATA": "AQ",  # Antarctica
    "ATF": "TF",  # French Southern Territories
    "ATG": "AG",  # Antigua and Barbuda
    "AUS": "AU",  # Australia
    "AUT": "AT",  # Austria
    "AZE": "AZ",  # Azerbaijan
    "BDI": "BI",  # Burundi
    "BEL": "BE",  # Belgium
    "BEN": "BJ",  # Benin
    "BES": "BQ",  # Bonaire, Sint Eustatius and Saba
    "BFA": "BF",  # Burkina Faso
    "BGD": "BD",  # Bangladesh
    "BGR": "BG",  # Bulgaria
    "BHR": "BH",  # Bahrain
    "BHS": "BS",  # Bahamas
    "BIH": "BA",  # Bosnia and Herzegovina
    "BLM": "BL",  # Saint Barthélemy
    "BLR": "BY",  # Belarus
    "BLZ": "BZ",  # Belize
    "BMU": "BM",  # Bermuda
    "BOL": "BO",  # Bolivia
    "BRA": "BR",  # Brazil
    "BRB": "BB",  # Barbados
    "BRN": "BN",  # Brunei Darussalam
    "BTN": "BT",  # Bhutan
    "BVT": "BV",  # Bouvet Island
    "BWA": "BW",  # Botswana
    "CAF": "CF",  # Central African Republic
    "CAN": "CA",  # Canada
    "CCK": "CC",  # Cocos (Keeling) Islands
    "CHE": "CH",  # Switzerland
    "CHL": "CL",  # Chile
    "CHN": "CN",  # China
    "CIV": "CI",  # Côte d'Ivoire
    "CMR": "CM",  # Cameroon
    "COD": "CD",  # Congo, The Democratic Republic of the
    "COG": "CG",  # Congo
    "COK": "CK",  # Cook Islands
    "COL": "CO",  # Colombia
    "COM": "KM",  # Comoros
    "CPV": "CV",  # Cabo Verde
    "CRI": "CR",  # Costa Rica
    "CUB": "CU",  # Cuba
    "CUW": "CW",  # Curaçao
    "CXR": "CX",  # Christmas Island
    "CYM": "KY",  # Cayman Islands
    "CYP": "CY",  # Cyprus
    "CZE": "CZ",  # Czechia
    "DEU": "DE",  # Germany
    "DJI": "DJ",  # Djibouti
    "DMA": "DM",  # Dominica
    "DNK": "DK",  # Denmark
    "DOM": "DO",  # Dominican Republic
    "DZA": "DZ",  # Algeria
    "ECU": "EC",  # Ecuador
    "EGY": "EG",  # Egypt
    "ERI": "ER",  # Eritrea
    "ESH": "EH",  # Western Sahara
    "ESP": "ES",  # Spain
    "EST": "EE",  # Estonia
    "ETH": "ET",  # Ethiopia
    "FIN": "FI",  # Finland
    "FJI": "FJ",  # Fiji
    "FLK": "FK",  # Falkland Islands (Malvinas)
    "FRA": "FR",  # France
    "FRO": "FO",  # Faroe Islands
    "FSM": "FM",  # Micronesia, Federated States of
    "GAB": "GA",  # Gabon
    "GBR": "GB",  # United Kingdom
    "GEO": "GE",  # Georgia
    "GGY": "GG",  # Guernsey
    "GHA": "GH",  # Ghana
    "GIB": "GI",  # Gibraltar
    "GIN": "GN",  # Guinea
    "GLP": "GP",  # Guadeloupe
    "GMB": "GM",  # Gambia
    "GNB": "GW",  # Guinea-Bissau
    "GNQ": "GQ",  # Equatorial Guinea
    "GRC": "GR",  # Greece
    "GRD": "GD",  # Grenada
    "GRL": "GL",  # Greenland
    "GTM": "GT",  # Guatemala
    "GUF": "GF",  # French Guiana
    "GUM": "GU",  # Guam
    "GUY": "GY",  # Guyana
    "HKG": "HK",  # Hong Kong
    "HMD": "HM",  # Heard Island and McDonald Islands
    "HND": "HN",  # Honduras
    "HRV": "HR",  # Croatia
    "HTI": "HT",  # Haiti
    "HUN": "HU",  # Hungary
    "IDN": "ID",  # Indonesia
    "IMN": "IM",  # Isle of Man
    "IND": "IN",  # India
    "IOT": "IO",  # British Indian Ocean Territory
    "IRL": "IE",  # Ireland
    "IRN": "IR",  # Iran
    "IRQ": "IQ",  # Iraq
    "ISL": "IS",  # Iceland
    "ISR": "IL",  # Israel
    "ITA": "IT",  # Italy
    "JAM": "JM",  # Jamaica
    "JEY": "JE",  # Jersey
    "JOR": "JO",  # Jordan
    "JPN": "JP",  # Japan
    "KAZ": "KZ",  # Kazakhstan
    "KEN": "KE",  # Kenya
    "KGZ": "KG",  # Kyrgyzstan
    "KHM": "KH",  # Cambodia
    "KIR": "KI",  # Kiribati
    "KNA": "KN",  # Saint Kitts and Nevis
    "KOR": "KR",  # South Korea
    "KWT": "KW",  # Kuwait
    "LAO": "LA",  # Laos
    "LBN": "LB",  # Lebanon
    "LBR": "LR",  # Liberia
    "LBY": "LY",  # Libya
    "LCA": "LC",  # Saint Lucia
    "LIE": "LI",  # Liechtenstein
    "LKA": "LK",  # Sri Lanka
    "LSO": "LS",  # Lesotho
    "LTU": "LT",  # Lithuania
    "LUX": "LU",  # Luxembourg
    "LVA": "LV",  # Latvia
    "MAC": "MO",  # Macao
    "MAF": "MF",  # Saint Martin (French part)
    "MAR": "MA",  # Morocco
    "MCO": "MC",  # Monaco
    "MDA": "MD",  # Moldova
    "MDG": "MG",  # Madagascar
    "MDV": "MV",  # Maldives
    "MEX": "MX",  # Mexico
    "MHL": "MH",  # Marshall Islands
    "MKD": "MK",  # North Macedonia
    "MLI": "ML",  # Mali
    "MLT": "MT",  # Malta
    "MMR": "MM",  # Myanmar
    "MNE": "ME",  # Montenegro
    "MNG": "MN",  # Mongolia
    "MNP": "MP",  # Northern Mariana Islands
    "MOZ": "MZ",  # Mozambique
    "MRT": "MR",  # Mauritania
    "MSR": "MS",  # Montserrat
    "MTQ": "MQ",  # Martinique
    "MUS": "MU",  # Mauritius
    "MWI": "MW",  # Malawi
    "MYS": "MY",  # Malaysia
    "MYT": "YT",  # Mayotte
    "NAM": "NA",  # Namibia
    "NCL": "NC",  # New Caledonia
    "NER": "NE",  # Niger
    "NFK": "NF",  # Norfolk Island
    "NGA": "NG",  # Nigeria
    "NIC": "NI",  # Nicaragua
    "NIU": "NU",  # Niue
    "NLD": "NL",  # Netherlands
    "NOR": "NO",  # Norway
    "NPL": "NP",  # Nepal
    "NRU": "NR",  # Nauru
    "NZL": "NZ",  # New Zealand
    "OMN": "OM",  # Oman
    "PAK": "PK",  # Pakistan
    "PAN": "PA",  # Panama
    "PCN": "PN",  # Pitcairn
    "PER": "PE",  # Peru
    "PHL": "PH",  # Philippines
    "PLW": "PW",  # Palau
    "PNG": "PG",  # Papua New Guinea
    "POL": "PL",  # Poland
    "PRI": "PR",  # Puerto Rico
    "PRK": "KP",  # North Korea
    "PRT": "PT",  # Portugal
    "PRY": "PY",  # Paraguay
    "PSE": "PS",  # Palestine, State of
    "PYF": "PF",  # French Polynesia
    "QAT": "QA",  # Qatar
    "REU": "RE",  # Réunion
    "ROU": "RO",  # Romania
    "RUS": "RU",  # Russian Federation
    "RWA": "RW",  # Rwanda
    "SAU": "SA",  # Saudi Arabia
    "SDN": "SD",  # Sudan
    "SEN": "SN",  # Senegal
    "SGP": "SG",  # Singapore
    "SGS": "GS",  # South Georgia and the South Sandwich Islands
    "SHN": "SH",  # Saint Helena, Ascension and Tristan da Cunha
    "SJM": "SJ",  # Svalbard and Jan Mayen
    "SLB": "SB",  # Solomon Islands
    "SLE": "SL",  # Sierra Leone
    "SLV": "SV",  # El Salvador
    "SMR": "SM",  # San Marino
    "SOM": "SO",  # Somalia
    "SPM": "PM",  # Saint Pierre and Miquelon
    "SRB": "RS",  # Serbia
    "SSD": "SS",  # South Sudan
    "STP": "ST",  # Sao Tome and Principe
    "SUR": "SR",  # Suriname
    "SVK": "SK",  # Slovakia
    "SVN": "SI",  # Slovenia
    "SWE": "SE",  # Sweden
    "SWZ": "SZ",  # Eswatini
    "SXM": "SX",  # Sint Maarten (Dutch part)
    "SYC": "SC",  # Seychelles
    "SYR": "SY",  # Syria
    "TCA": "TC",  # Turks and Caicos Islands
    "TCD": "TD",  # Chad
    "TGO": "TG",  # Togo
    "THA": "TH",  # Thailand
    "TJK": "TJ",  # Tajikistan
    "TKL": "TK",  # Tokelau
    "TKM": "TM",  # Turkmenistan
    "TLS": "TL",  # Timor-Leste
    "TON": "TO",  # Tonga
    "TTO": "TT",  # Trinidad and Tobago
    "TUN": "TN",  # Tunisia
    "TUR": "TR",  # Türkiye
    "TUV": "TV",  # Tuvalu
    "TWN": "TW",  # Taiwan
    "TZA": "TZ",  # Tanzania
    "UGA": "UG",  # Uganda
    "UKR": "UA",  # Ukraine
    "UMI": "UM",  # United States Minor Outlying Islands
    "URY": "UY",  # Uruguay
    "USA": "US",  # United States
    "UZB": "UZ",  # Uzbekistan
    "VAT": "VA",  # Holy See (Vatican City State)
    "VCT": "VC",  # Saint Vincent and the Grenadines
    "VEN": "VE",  # Venezuela
    "VGB": "VG",  # Virgin Islands, British
    "VIR": "VI",  # Virgin Islands, U.S.
    "VNM": "VN",  # Vietnam
    "VUT": "VU",  # Vanuatu
    "WLF": "WF",  # Wallis and Futuna
    "WSM": "WS",  # Samoa
    "XKO": "XK",  # Kosovo (GADM code; ISO has no alpha-3)
    "YEM": "YE",  # Yemen
    "ZAF": "ZA",  # South Africa
    "ZMB": "ZM",  # Zambia
    "ZWE": "ZW",  # Zimbabwe
}
