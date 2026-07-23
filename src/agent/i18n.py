"""Templated translations for the static scaffolding around tool-generated
user-facing messages (the "human_feedback" ToolMessages shown directly to
the user — see msg_type in src.agent.tools.common and friends).

The LLM-generated *content* embedded in these messages (an insight's prose,
a dataset-selection `reason`, a chart title, …) is already produced in the
conversation language by threading `language` into the relevant prompts
(see src.agent.language). This module covers everything else: the fixed
labels and sentences those tools wrap around that content (e.g. "Key
Finding:", "No dataset selected: …"), which would otherwise always render
in English regardless of conversation language.

Pre-built translations cover the languages users can actually select as a
profile preference (see src.api.user_profile_configs.languages.LANGUAGES).
Any other language (typically detected from the query text rather than
chosen) falls back to translating the English template on the fly via the
small model, once per (key, language) for the life of the process.
"""

from typing import Optional

from src.agent.language import DEFAULT_LANGUAGE, language_name
from src.agent.llms import SMALL_MODEL
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Message id -> {language code -> template}. Every language's template must
# accept the same `{placeholder}` names as the "en" entry.
MESSAGES: dict[str, dict[str, str]] = {
    "analyst.generated_charts": {
        "en": "Generated {count} chart(s)",
        "es": "Se generaron {count} gráfico(s)",
        "fr": "{count} graphique(s) généré(s)",
        "pt": "Foram gerados {count} gráfico(s)",
        "id": "{count} bagan dibuat",
    },
    "analyst.key_finding": {
        "en": "Key Finding: {text}",
        "es": "Hallazgo clave: {text}",
        "fr": "Constat clé : {text}",
        "pt": "Principal constatação: {text}",
        "id": "Temuan utama: {text}",
    },
    "analyst.chart_label": {
        "en": "Chart {idx}: {title}",
        "es": "Gráfico {idx}: {title}",
        "fr": "Graphique {idx} : {title}",
        "pt": "Gráfico {idx}: {title}",
        "id": "Bagan {idx}: {title}",
    },
    "analyst.chart_data_csv_header": {
        "en": "Chart data CSV:",
        "es": "CSV de datos del gráfico:",
        "fr": "CSV des données du graphique :",
        "pt": "CSV dos dados do gráfico:",
        "id": "CSV data bagan:",
    },
    "analyst.dataset_cautions_header": {
        "en": "Dataset cautions:",
        "es": "Advertencias del conjunto de datos:",
        "fr": "Mises en garde sur le jeu de données :",
        "pt": "Ressalvas do conjunto de dados:",
        "id": "Peringatan dataset:",
    },
    "analyst.follow_up_header": {
        "en": "Follow-up suggestions:",
        "es": "Sugerencias de seguimiento:",
        "fr": "Suggestions de suivi :",
        "pt": "Sugestões de acompanhamento:",
        "id": "Saran lanjutan:",
    },
    "pick_dataset.no_single_match": {
        "en": "No single dataset directly matches the query. {reason}",
        "es": "Ningún conjunto de datos único coincide directamente con la consulta. {reason}",
        "fr": "Aucun jeu de données unique ne correspond directement à la requête. {reason}",
        "pt": "Nenhum conjunto de dados único corresponde diretamente à consulta. {reason}",
        "id": "Tidak ada satu dataset pun yang secara langsung cocok dengan permintaan ini. {reason}",
    },
    "pick_dataset.closest_options_header": {
        "en": "Here are the closest available options:",
        "es": "Estas son las opciones disponibles más cercanas:",
        "fr": "Voici les options disponibles les plus proches :",
        "pt": "Aqui estão as opções disponíveis mais próximas:",
        "id": "Berikut ini adalah opsi yang tersedia paling mendekati:",
    },
    "pick_dataset.no_match": {
        "en": "No dataset selected: {reason}",
        "es": "No se seleccionó ningún conjunto de datos: {reason}",
        "fr": "Aucun jeu de données sélectionné : {reason}",
        "pt": "Nenhum conjunto de dados selecionado: {reason}",
        "id": "Tidak ada dataset yang dipilih: {reason}",
    },
    "pull_data.date_out_of_range": {
        "en": "The requested date range ({start_date} to {end_date}) is outside the available range for {dataset_name} (available: {available_start} to {available_end}). Please choose dates within this range.",
        "es": "El rango de fechas solicitado ({start_date} a {end_date}) está fuera del rango disponible para {dataset_name} (disponible: {available_start} a {available_end}). Por favor, elija fechas dentro de este rango.",
        "fr": "La plage de dates demandée ({start_date} à {end_date}) est hors de la plage disponible pour {dataset_name} (disponible : {available_start} à {available_end}). Veuillez choisir des dates dans cette plage.",
        "pt": "O intervalo de datas solicitado ({start_date} a {end_date}) está fora do intervalo disponível para {dataset_name} (disponível: {available_start} a {available_end}). Escolha datas dentro desse intervalo.",
        "id": "Rentang tanggal yang diminta ({start_date} hingga {end_date}) berada di luar rentang yang tersedia untuk {dataset_name} (tersedia: {available_start} hingga {available_end}). Silakan pilih tanggal dalam rentang ini.",
    },
    "pull_data.no_data": {
        "en": "No data found for the selected AOIs and dataset {dataset_name}.",
        "es": "No se encontraron datos para las áreas de interés seleccionadas y el conjunto de datos {dataset_name}.",
        "fr": "Aucune donnée trouvée pour les zones d'intérêt sélectionnées et le jeu de données {dataset_name}.",
        "pt": "Nenhum dado encontrado para as áreas de interesse selecionadas e o conjunto de dados {dataset_name}.",
        "id": "Tidak ada data yang ditemukan untuk AOI yang dipilih dan dataset {dataset_name}.",
    },
    "show_imagery.no_aoi": {
        "en": "No AOI selected. Run pick_aoi before requesting satellite imagery.",
        "es": "No se seleccionó ningún área de interés. Ejecute pick_aoi antes de solicitar imágenes satelitales.",
        "fr": "Aucune zone d'intérêt sélectionnée. Exécutez pick_aoi avant de demander des images satellite.",
        "pt": "Nenhuma área de interesse selecionada. Execute pick_aoi antes de solicitar imagens de satélite.",
        "id": "Tidak ada AOI yang dipilih. Jalankan pick_aoi sebelum meminta citra satelit.",
    },
    "show_imagery.invalid_date": {
        "en": "Invalid target_date '{target_date}'. Use YYYY-MM-DD.",
        "es": "target_date no válido '{target_date}'. Use el formato AAAA-MM-DD.",
        "fr": "target_date invalide '{target_date}'. Utilisez le format AAAA-MM-JJ.",
        "pt": "target_date inválido '{target_date}'. Use o formato AAAA-MM-DD.",
        "id": "target_date tidak valid '{target_date}'. Gunakan format YYYY-MM-DD.",
    },
    "show_imagery.geometry_error": {
        "en": "Could not load the geometry of the selected AOI.",
        "es": "No se pudo cargar la geometría del área de interés seleccionada.",
        "fr": "Impossible de charger la géométrie de la zone d'intérêt sélectionnée.",
        "pt": "Não foi possível carregar a geometria da área de interesse selecionada.",
        "id": "Tidak dapat memuat geometri AOI yang dipilih.",
    },
    "show_imagery.aoi_too_large": {
        "en": "Selected area is too large: {error}",
        "es": "El área seleccionada es demasiado grande: {error}",
        "fr": "La zone sélectionnée est trop grande : {error}",
        "pt": "A área selecionada é muito grande: {error}",
        "id": "Area yang dipilih terlalu besar: {error}",
    },
    "show_imagery.no_scenes_found": {
        "en": "No Sentinel-2 scenes with under {cloud_cover}% cloud cover found within ±{window_days} days of {target_date}. Suggest to the user: widen the search window (window_days), allow cloudier scenes (max_cloud_cover) or pick a different date — then retry with their choice.",
        "es": "No se encontraron escenas de Sentinel-2 con menos del {cloud_cover}% de cobertura de nubes dentro de ±{window_days} días de {target_date}. Sugiera al usuario: ampliar la ventana de búsqueda (window_days), permitir escenas más nubladas (max_cloud_cover) o elegir una fecha diferente, y luego vuelva a intentarlo con su elección.",
        "fr": "Aucune scène Sentinel-2 avec moins de {cloud_cover} % de couverture nuageuse trouvée dans un intervalle de ±{window_days} jours autour du {target_date}. Suggérez à l'utilisateur : d'élargir la fenêtre de recherche (window_days), d'autoriser des scènes plus nuageuses (max_cloud_cover) ou de choisir une autre date — puis réessayez avec son choix.",
        "pt": "Nenhuma cena Sentinel-2 com menos de {cloud_cover}% de cobertura de nuvens foi encontrada dentro de ±{window_days} dias de {target_date}. Sugira ao usuário: ampliar a janela de busca (window_days), permitir cenas mais nubladas (max_cloud_cover) ou escolher outra data — depois tente novamente com a escolha dele.",
        "id": "Tidak ditemukan citra Sentinel-2 dengan tutupan awan di bawah {cloud_cover}% dalam rentang ±{window_days} hari dari {target_date}. Sarankan kepada pengguna untuk: memperlebar jendela pencarian (window_days), mengizinkan citra yang lebih berawan (max_cloud_cover), atau memilih tanggal lain — lalu coba lagi dengan pilihan mereka.",
    },
    "show_imagery.stac_unavailable": {
        "en": "The Sentinel-2 catalog is currently unavailable. Try again later.",
        "es": "El catálogo de Sentinel-2 no está disponible actualmente. Inténtelo de nuevo más tarde.",
        "fr": "Le catalogue Sentinel-2 est actuellement indisponible. Réessayez plus tard.",
        "pt": "O catálogo do Sentinel-2 está atualmente indisponível. Tente novamente mais tarde.",
        "id": "Katalog Sentinel-2 saat ini tidak tersedia. Coba lagi nanti.",
    },
    "show_imagery.unexpected_error": {
        "en": "Something went wrong while building the satellite imagery layer. Please try again later.",
        "es": "Algo salió mal al crear la capa de imágenes satelitales. Por favor, inténtelo de nuevo más tarde.",
        "fr": "Une erreur s'est produite lors de la création de la couche d'imagerie satellite. Veuillez réessayer plus tard.",
        "pt": "Algo deu errado ao criar a camada de imagens de satélite. Tente novamente mais tarde.",
        "id": "Terjadi kesalahan saat membuat layer citra satelit. Silakan coba lagi nanti.",
    },
    "show_imagery.success": {
        "en": "Sentinel-2 imagery layer created for {aois}{summary} and shown on the map.",
        "es": "Se creó la capa de imágenes Sentinel-2 para {aois}{summary} y se mostró en el mapa.",
        "fr": "La couche d'imagerie Sentinel-2 a été créée pour {aois}{summary} et affichée sur la carte.",
        "pt": "A camada de imagens Sentinel-2 foi criada para {aois}{summary} e exibida no mapa.",
        "id": "Layer citra Sentinel-2 untuk {aois}{summary} telah dibuat dan ditampilkan di peta.",
    },
    "show_imagery.success_summary": {
        "en": " from {count} scenes acquired between {start} and {end}",
        "es": " a partir de {count} escenas adquiridas entre {start} y {end}",
        "fr": " à partir de {count} scènes acquises entre le {start} et le {end}",
        "pt": " a partir de {count} cenas adquiridas entre {start} e {end}",
        "id": " dari {count} citra yang diperoleh antara {start} dan {end}",
    },
    "pick_aoi.no_place": {
        "en": "I couldn't identify a place in your request. Which area would you like me to analyze?",
        "es": "No pude identificar un lugar en su solicitud. ¿Qué área le gustaría que analice?",
        "fr": "Je n'ai pas pu identifier de lieu dans votre demande. Quelle zone souhaitez-vous que j'analyse ?",
        "pt": "Não consegui identificar um local em sua solicitação. Qual área você gostaria que eu analisasse?",
        "id": "Saya tidak dapat mengidentifikasi lokasi dalam permintaan Anda. Area mana yang ingin Anda analisis?",
    },
    "pick_aoi.no_matching_aois": {
        "en": "No matching AOIs were found for your request. Try a broader place name or choose a different subregion type.",
        "es": "No se encontraron áreas de interés que coincidan con su solicitud. Intente con un nombre de lugar más amplio o elija un tipo de subregión diferente.",
        "fr": "Aucune zone d'intérêt correspondante n'a été trouvée pour votre demande. Essayez un nom de lieu plus large ou choisissez un autre type de sous-région.",
        "pt": "Nenhuma área de interesse correspondente foi encontrada para sua solicitação. Tente um nome de local mais amplo ou escolha um tipo de subregião diferente.",
        "id": "Tidak ditemukan AOI yang cocok untuk permintaan Anda. Coba nama tempat yang lebih luas atau pilih jenis subregion yang berbeda.",
    },
    "pick_aoi.multiple_sources": {
        "en": "Found multiple sources of AOIs, which is not supported. Please select only one source.",
        "es": "Se encontraron múltiples fuentes de áreas de interés, lo cual no es compatible. Seleccione solo una fuente.",
        "fr": "Plusieurs sources de zones d'intérêt ont été trouvées, ce qui n'est pas pris en charge. Veuillez sélectionner une seule source.",
        "pt": "Foram encontradas várias fontes de áreas de interesse, o que não é suportado. Selecione apenas uma fonte.",
        "id": "Ditemukan beberapa sumber AOI, yang tidak didukung. Silakan pilih hanya satu sumber.",
    },
    "pick_aoi.too_many_subregions": {
        "en": "Found {count} subregions, which is too many to process efficiently. Please narrow down your search by either:\n1. Being more specific with the AOI selection (choose a smaller area)\n2. Being more specific with the subregion query (e.g., 'kbas' instead of 'areas')\nFor optimal performance, please limit results to under {subregion_limit} subregions for KBA, WDPA, and Indigenous Lands, or under {subregion_limit_admin} for other area types.",
        "es": "Se encontraron {count} subregiones, lo cual es demasiado para procesar de forma eficiente. Reduzca su búsqueda de una de estas formas:\n1. Siendo más específico con la selección del área de interés (elija un área más pequeña)\n2. Siendo más específico con la consulta de subregión (por ejemplo, 'kbas' en lugar de 'áreas')\nPara un rendimiento óptimo, limite los resultados a menos de {subregion_limit} subregiones para KBA, WDPA y Tierras Indígenas, o menos de {subregion_limit_admin} para otros tipos de área.",
        "fr": "{count} sous-régions trouvées, ce qui est trop pour un traitement efficace. Veuillez affiner votre recherche en :\n1. Étant plus précis dans la sélection de la zone d'intérêt (choisissez une zone plus petite)\n2. Étant plus précis dans la requête de sous-région (par exemple, « kbas » au lieu de « zones »)\nPour des performances optimales, limitez les résultats à moins de {subregion_limit} sous-régions pour les KBA, WDPA et terres autochtones, ou à moins de {subregion_limit_admin} pour les autres types de zones.",
        "pt": "Foram encontradas {count} subregiões, o que é demais para processar com eficiência. Restrinja sua busca de uma das seguintes formas:\n1. Sendo mais específico na seleção da área de interesse (escolha uma área menor)\n2. Sendo mais específico na consulta de subregião (por exemplo, 'kbas' em vez de 'áreas')\nPara um desempenho ideal, limite os resultados a menos de {subregion_limit} subregiões para KBA, WDPA e Terras Indígenas, ou menos de {subregion_limit_admin} para outros tipos de área.",
        "id": "Ditemukan {count} subregion, yang terlalu banyak untuk diproses secara efisien. Persempit pencarian Anda dengan salah satu cara berikut:\n1. Lebih spesifik dalam pemilihan AOI (pilih area yang lebih kecil)\n2. Lebih spesifik dalam kueri subregion (misalnya, 'kbas' bukan 'areas')\nUntuk performa optimal, batasi hasil hingga kurang dari {subregion_limit} subregion untuk KBA, WDPA, dan Wilayah Adat, atau kurang dari {subregion_limit_admin} untuk jenis area lainnya.",
    },
    "pick_aoi.duplicate_names": {
        "en": "I found multiple locations named '{short_name}' in different countries. Please tell me which one you meant:\n\n{candidate_names}\n\nWhich location are you looking for?",
        "es": "Encontré varios lugares llamados '{short_name}' en diferentes países. Indíqueme cuál quiso decir:\n\n{candidate_names}\n\n¿Qué ubicación está buscando?",
        "fr": "J'ai trouvé plusieurs lieux nommés « {short_name} » dans différents pays. Merci de préciser lequel vous vouliez dire :\n\n{candidate_names}\n\nQuel emplacement recherchez-vous ?",
        "pt": "Encontrei vários locais chamados '{short_name}' em países diferentes. Diga-me qual deles você quis dizer:\n\n{candidate_names}\n\nQual local você está procurando?",
        "id": "Saya menemukan beberapa lokasi bernama '{short_name}' di negara yang berbeda. Beri tahu saya mana yang Anda maksud:\n\n{candidate_names}\n\nLokasi mana yang Anda cari?",
    },
    "pick_aoi.global_subregion_country_only": {
        "en": "Global queries only support subregion='country'. Please set subregion='country' to compare across all countries.",
        "es": "Las consultas globales solo admiten subregion='country'. Establezca subregion='country' para comparar entre todos los países.",
        "fr": "Les requêtes globales ne prennent en charge que subregion='country'. Définissez subregion='country' pour comparer tous les pays.",
        "pt": "As consultas globais só suportam subregion='country'. Defina subregion='country' para comparar entre todos os países.",
        "id": "Kueri global hanya mendukung subregion='country'. Setel subregion='country' untuk membandingkan seluruh negara.",
    },
}

# On-the-fly translations of templates for languages outside MESSAGES, keyed
# by (message key, language code). Populated lazily by `t()`; lives for the
# process lifetime, same tradeoff as the retriever/model caches in
# src.agent.subagents.pick_dataset.tool.
_translation_cache: dict[tuple[str, str], str] = {}


def _extract_text(content) -> str:
    """Normalize a LangChain message `.content` (str, or a list of text /
    content-block parts, depending on provider) into plain text."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "".join(parts)


async def _translate_template(key: str, english: str, language: str) -> str:
    cache_key = (key, language)
    cached = _translation_cache.get(cache_key)
    if cached is not None:
        return cached

    prompt = (
        f"Translate the following message template into {language_name(language)}. "
        "It contains placeholders like {{name}} written with curly braces — "
        "copy every placeholder exactly as-is (same braces, same name, same "
        "position makes sense in the translation) and translate only the "
        "surrounding natural-language text. Reply with only the translated "
        "template, no explanation.\n\n"
        f"Template:\n{english}"
    )
    try:
        response = await SMALL_MODEL.ainvoke(prompt)
        translated = _extract_text(response.content).strip() or english
    except Exception:
        logger.exception("i18n_translation_failed", key=key, language=language)
        translated = english

    _translation_cache[cache_key] = translated
    return translated


async def t(key: str, language: Optional[str] = None, **kwargs) -> str:
    """Render message `key` in `language`, formatting in `kwargs`.

    Falls back to English if `key` is unknown. For a `language` not in
    MESSAGES[key], translates the English template on the fly (cached
    thereafter) rather than rendering in English.
    """
    templates = MESSAGES.get(key)
    if templates is None:
        logger.warning("i18n_missing_key", key=key)
        return ""

    language = language or DEFAULT_LANGUAGE
    template = templates.get(language)
    if template is None:
        template = await _translate_template(
            key, templates[DEFAULT_LANGUAGE], language
        )
    return template.format(**kwargs)
