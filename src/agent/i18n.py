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

Pre-built translations cover the languages users can select as a profile
preference (see src.api.user_profile_configs.languages.LANGUAGES) plus a
broader set of commonly query-detected languages. Any other language falls
back to translating the English template on the fly via the small model,
once per (key, language) for the life of the process.
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
        "de": "{count} Diagramm(e) erstellt",
        "it": "{count} grafico/i generato/i",
        "nl": "{count} grafiek(en) gegenereerd",
        "ru": "Создано {count} график(ов)",
        "zh": "已生成 {count} 个图表",
        "ar": "تم إنشاء {count} مخطط(ات)",
        "hi": "{count} चार्ट बनाए गए",
        "vi": "Đã tạo {count} biểu đồ",
        "sw": "Chati {count} zimetengenezwa",
        "tr": "{count} grafik oluşturuldu",
    },
    "analyst.key_finding": {
        "en": "Key Finding: {text}",
        "es": "Hallazgo clave: {text}",
        "fr": "Constat clé : {text}",
        "pt": "Principal constatação: {text}",
        "id": "Temuan utama: {text}",
        "de": "Wichtigste Erkenntnis: {text}",
        "it": "Risultato principale: {text}",
        "nl": "Belangrijkste bevinding: {text}",
        "ru": "Ключевой вывод: {text}",
        "zh": "关键发现：{text}",
        "ar": "أهم استنتاج: {text}",
        "hi": "मुख्य निष्कर्ष: {text}",
        "vi": "Phát hiện chính: {text}",
        "sw": "Ugunduzi mkuu: {text}",
        "tr": "Önemli bulgu: {text}",
    },
    "analyst.chart_label": {
        "en": "Chart {idx}: {title}",
        "es": "Gráfico {idx}: {title}",
        "fr": "Graphique {idx} : {title}",
        "pt": "Gráfico {idx}: {title}",
        "id": "Bagan {idx}: {title}",
        "de": "Diagramm {idx}: {title}",
        "it": "Grafico {idx}: {title}",
        "nl": "Grafiek {idx}: {title}",
        "ru": "График {idx}: {title}",
        "zh": "图表 {idx}：{title}",
        "ar": "المخطط {idx}: {title}",
        "hi": "चार्ट {idx}: {title}",
        "vi": "Biểu đồ {idx}: {title}",
        "sw": "Chati {idx}: {title}",
        "tr": "Grafik {idx}: {title}",
    },
    "analyst.chart_data_csv_header": {
        "en": "Chart data CSV:",
        "es": "CSV de datos del gráfico:",
        "fr": "CSV des données du graphique :",
        "pt": "CSV dos dados do gráfico:",
        "id": "CSV data bagan:",
        "de": "CSV der Diagrammdaten:",
        "it": "CSV dei dati del grafico:",
        "nl": "CSV van grafiekgegevens:",
        "ru": "CSV данных графика:",
        "zh": "图表数据 CSV：",
        "ar": "ملف CSV لبيانات المخطط:",
        "hi": "चार्ट डेटा CSV:",
        "vi": "CSV dữ liệu biểu đồ:",
        "sw": "CSV ya data ya chati:",
        "tr": "Grafik verisi CSV:",
    },
    "analyst.dataset_cautions_header": {
        "en": "Dataset cautions:",
        "es": "Advertencias del conjunto de datos:",
        "fr": "Mises en garde sur le jeu de données :",
        "pt": "Ressalvas do conjunto de dados:",
        "id": "Peringatan dataset:",
        "de": "Hinweise zum Datensatz:",
        "it": "Avvertenze sul set di dati:",
        "nl": "Waarschuwingen bij de dataset:",
        "ru": "Предостережения по набору данных:",
        "zh": "数据集注意事项：",
        "ar": "تحذيرات مجموعة البيانات:",
        "hi": "डेटासेट सावधानियाँ:",
        "vi": "Lưu ý về bộ dữ liệu:",
        "sw": "Tahadhari za dataset:",
        "tr": "Veri kümesi uyarıları:",
    },
    "analyst.follow_up_header": {
        "en": "Follow-up suggestions:",
        "es": "Sugerencias de seguimiento:",
        "fr": "Suggestions de suivi :",
        "pt": "Sugestões de acompanhamento:",
        "id": "Saran lanjutan:",
        "de": "Weiterführende Vorschläge:",
        "it": "Suggerimenti di approfondimento:",
        "nl": "Vervolgsuggesties:",
        "ru": "Дополнительные предложения:",
        "zh": "后续建议：",
        "ar": "مقترحات المتابعة:",
        "hi": "अनुवर्ती सुझाव:",
        "vi": "Gợi ý tiếp theo:",
        "sw": "Mapendekezo ya ufuatiliaji:",
        "tr": "Takip önerileri:",
    },
    "pick_dataset.no_single_match": {
        "en": "No single dataset directly matches the query. {reason}",
        "es": "Ningún conjunto de datos único coincide directamente con la consulta. {reason}",
        "fr": "Aucun jeu de données unique ne correspond directement à la requête. {reason}",
        "pt": "Nenhum conjunto de dados único corresponde diretamente à consulta. {reason}",
        "id": "Tidak ada satu dataset pun yang secara langsung cocok dengan permintaan ini. {reason}",
        "de": "Kein einzelner Datensatz passt direkt zur Anfrage. {reason}",
        "it": "Nessun singolo set di dati corrisponde direttamente alla richiesta. {reason}",
        "nl": "Geen enkele dataset komt direct overeen met de vraag. {reason}",
        "ru": "Ни один набор данных не полностью соответствует запросу. {reason}",
        "zh": "没有单一数据集直接匹配该查询。{reason}",
        "ar": "لا توجد مجموعة بيانات واحدة تطابق الاستعلام مباشرة. {reason}",
        "hi": "कोई एक डेटासेट सीधे प्रश्न से मेल नहीं खाता। {reason}",
        "vi": "Không có bộ dữ liệu nào khớp trực tiếp với yêu cầu. {reason}",
        "sw": "Hakuna dataset moja inayolingana moja kwa moja na ombi hili. {reason}",
        "tr": "Sorguya doğrudan uyan tek bir veri kümesi yok. {reason}",
    },
    "pick_dataset.closest_options_header": {
        "en": "Here are the closest available options:",
        "es": "Estas son las opciones disponibles más cercanas:",
        "fr": "Voici les options disponibles les plus proches :",
        "pt": "Aqui estão as opções disponíveis mais próximas:",
        "id": "Berikut ini adalah opsi yang tersedia paling mendekati:",
        "de": "Hier sind die nächstgelegenen verfügbaren Optionen:",
        "it": "Ecco le opzioni disponibili più vicine:",
        "nl": "Hier zijn de meest geschikte beschikbare opties:",
        "ru": "Вот наиболее подходящие доступные варианты:",
        "zh": "以下是最接近的可用选项：",
        "ar": "فيما يلي أقرب الخيارات المتاحة:",
        "hi": "यहाँ निकटतम उपलब्ध विकल्प दिए गए हैं:",
        "vi": "Đây là các lựa chọn khả dụng gần nhất:",
        "sw": "Hizi ni chaguo zilizo karibu zaidi zinazopatikana:",
        "tr": "İşte en yakın mevcut seçenekler:",
    },
    "pick_dataset.no_match": {
        "en": "No dataset selected: {reason}",
        "es": "No se seleccionó ningún conjunto de datos: {reason}",
        "fr": "Aucun jeu de données sélectionné : {reason}",
        "pt": "Nenhum conjunto de dados selecionado: {reason}",
        "id": "Tidak ada dataset yang dipilih: {reason}",
        "de": "Kein Datensatz ausgewählt: {reason}",
        "it": "Nessun set di dati selezionato: {reason}",
        "nl": "Geen dataset geselecteerd: {reason}",
        "ru": "Набор данных не выбран: {reason}",
        "zh": "未选择数据集：{reason}",
        "ar": "لم يتم اختيار مجموعة بيانات: {reason}",
        "hi": "कोई डेटासेट चयनित नहीं: {reason}",
        "vi": "Không có bộ dữ liệu nào được chọn: {reason}",
        "sw": "Hakuna dataset iliyochaguliwa: {reason}",
        "tr": "Veri kümesi seçilmedi: {reason}",
    },
    "pull_data.date_out_of_range": {
        "en": "The requested date range ({start_date} to {end_date}) is outside the available range for {dataset_name} (available: {available_start} to {available_end}). Please choose dates within this range.",
        "es": "El rango de fechas solicitado ({start_date} a {end_date}) está fuera del rango disponible para {dataset_name} (disponible: {available_start} a {available_end}). Por favor, elija fechas dentro de este rango.",
        "fr": "La plage de dates demandée ({start_date} à {end_date}) est hors de la plage disponible pour {dataset_name} (disponible : {available_start} à {available_end}). Veuillez choisir des dates dans cette plage.",
        "pt": "O intervalo de datas solicitado ({start_date} a {end_date}) está fora do intervalo disponível para {dataset_name} (disponível: {available_start} a {available_end}). Escolha datas dentro desse intervalo.",
        "id": "Rentang tanggal yang diminta ({start_date} hingga {end_date}) berada di luar rentang yang tersedia untuk {dataset_name} (tersedia: {available_start} hingga {available_end}). Silakan pilih tanggal dalam rentang ini.",
        "de": "Der angeforderte Zeitraum ({start_date} bis {end_date}) liegt außerhalb des verfügbaren Bereichs für {dataset_name} (verfügbar: {available_start} bis {available_end}). Bitte wählen Sie Daten innerhalb dieses Bereichs.",
        "it": "L'intervallo di date richiesto ({start_date} - {end_date}) è fuori dall'intervallo disponibile per {dataset_name} (disponibile: {available_start} - {available_end}). Scegliere date comprese in questo intervallo.",
        "nl": "De opgevraagde periode ({start_date} tot {end_date}) valt buiten het beschikbare bereik voor {dataset_name} (beschikbaar: {available_start} tot {available_end}). Kies data binnen dit bereik.",
        "ru": "Запрошенный диапазон дат ({start_date}–{end_date}) выходит за пределы доступного диапазона для {dataset_name} (доступно: {available_start}–{available_end}). Пожалуйста, выберите даты в пределах этого диапазона.",
        "zh": "请求的日期范围（{start_date} 至 {end_date}）超出了 {dataset_name} 的可用范围（可用：{available_start} 至 {available_end}）。请选择该范围内的日期。",
        "ar": "نطاق التواريخ المطلوب ({start_date} إلى {end_date}) يقع خارج النطاق المتاح لـ {dataset_name} (المتاح: {available_start} إلى {available_end}). يرجى اختيار تواريخ ضمن هذا النطاق.",
        "hi": "अनुरोधित तिथि सीमा ({start_date} से {end_date}) {dataset_name} के लिए उपलब्ध सीमा से बाहर है (उपलब्ध: {available_start} से {available_end})। कृपया इस सीमा के भीतर तिथियाँ चुनें।",
        "vi": "Khoảng thời gian yêu cầu ({start_date} đến {end_date}) nằm ngoài phạm vi khả dụng của {dataset_name} (khả dụng: {available_start} đến {available_end}). Vui lòng chọn ngày trong phạm vi này.",
        "sw": "Kipindi cha tarehe kilichoombwa ({start_date} hadi {end_date}) kiko nje ya kipindi kinachopatikana kwa {dataset_name} (kinachopatikana: {available_start} hadi {available_end}). Tafadhali chagua tarehe ndani ya kipindi hiki.",
        "tr": "İstenen tarih aralığı ({start_date} - {end_date}), {dataset_name} için mevcut aralığın dışında (mevcut: {available_start} - {available_end}). Lütfen bu aralıktaki tarihleri seçin.",
    },
    "pull_data.no_data": {
        "en": "No data found for the selected AOIs and dataset {dataset_name}.",
        "es": "No se encontraron datos para las áreas de interés seleccionadas y el conjunto de datos {dataset_name}.",
        "fr": "Aucune donnée trouvée pour les zones d'intérêt sélectionnées et le jeu de données {dataset_name}.",
        "pt": "Nenhum dado encontrado para as áreas de interesse selecionadas e o conjunto de dados {dataset_name}.",
        "id": "Tidak ada data yang ditemukan untuk AOI yang dipilih dan dataset {dataset_name}.",
        "de": "Für die ausgewählten Interessengebiete und den Datensatz {dataset_name} wurden keine Daten gefunden.",
        "it": "Nessun dato trovato per le aree di interesse selezionate e il set di dati {dataset_name}.",
        "nl": "Geen gegevens gevonden voor de geselecteerde interessegebieden en dataset {dataset_name}.",
        "ru": "Данные не найдены для выбранных зон интереса и набора данных {dataset_name}.",
        "zh": "未找到所选兴趣区域和数据集 {dataset_name} 的数据。",
        "ar": "لم يتم العثور على بيانات للمناطق المحددة ومجموعة البيانات {dataset_name}.",
        "hi": "चयनित AOI और डेटासेट {dataset_name} के लिए कोई डेटा नहीं मिला।",
        "vi": "Không tìm thấy dữ liệu cho các khu vực quan tâm đã chọn và bộ dữ liệu {dataset_name}.",
        "sw": "Hakuna data iliyopatikana kwa AOI zilizochaguliwa na dataset {dataset_name}.",
        "tr": "Seçilen ilgi alanları ve {dataset_name} veri kümesi için veri bulunamadı.",
    },
    "show_imagery.no_aoi": {
        "en": "No AOI selected. Run pick_aoi before requesting satellite imagery.",
        "es": "No se seleccionó ningún área de interés. Ejecute pick_aoi antes de solicitar imágenes satelitales.",
        "fr": "Aucune zone d'intérêt sélectionnée. Exécutez pick_aoi avant de demander des images satellite.",
        "pt": "Nenhuma área de interesse selecionada. Execute pick_aoi antes de solicitar imagens de satélite.",
        "id": "Tidak ada AOI yang dipilih. Jalankan pick_aoi sebelum meminta citra satelit.",
        "de": "Kein Interessengebiet ausgewählt. Führen Sie pick_aoi aus, bevor Sie Satellitenbilder anfordern.",
        "it": "Nessuna area di interesse selezionata. Eseguire pick_aoi prima di richiedere immagini satellitari.",
        "nl": "Geen interessegebied geselecteerd. Voer pick_aoi uit voordat u satellietbeelden aanvraagt.",
        "ru": "Зона интереса не выбрана. Выполните pick_aoi перед запросом спутниковых снимков.",
        "zh": "未选择兴趣区域。请先运行 pick_aoi，然后再请求卫星图像。",
        "ar": "لم يتم تحديد منطقة اهتمام. قم بتشغيل pick_aoi قبل طلب صور الأقمار الصناعية.",
        "hi": "कोई AOI चयनित नहीं है। उपग्रह इमेजरी का अनुरोध करने से पहले pick_aoi चलाएँ।",
        "vi": "Chưa chọn khu vực quan tâm. Chạy pick_aoi trước khi yêu cầu ảnh vệ tinh.",
        "sw": "Hakuna AOI iliyochaguliwa. Tekeleza pick_aoi kabla ya kuomba picha za setelaiti.",
        "tr": "İlgi alanı seçilmedi. Uydu görüntüsü istemeden önce pick_aoi'yi çalıştırın.",
    },
    "show_imagery.invalid_date": {
        "en": "Invalid target_date '{target_date}'. Use YYYY-MM-DD.",
        "es": "target_date no válido '{target_date}'. Use el formato AAAA-MM-DD.",
        "fr": "target_date invalide '{target_date}'. Utilisez le format AAAA-MM-JJ.",
        "pt": "target_date inválido '{target_date}'. Use o formato AAAA-MM-DD.",
        "id": "target_date tidak valid '{target_date}'. Gunakan format YYYY-MM-DD.",
        "de": "Ungültiges target_date '{target_date}'. Verwenden Sie JJJJ-MM-TT.",
        "it": "target_date non valido '{target_date}'. Usare il formato AAAA-MM-GG.",
        "nl": "Ongeldige target_date '{target_date}'. Gebruik JJJJ-MM-DD.",
        "ru": "Недопустимая дата target_date '{target_date}'. Используйте формат ГГГГ-ММ-ДД.",
        "zh": "target_date 无效 '{target_date}'。请使用 YYYY-MM-DD 格式。",
        "ar": "target_date غير صالح '{target_date}'. استخدم التنسيق YYYY-MM-DD.",
        "hi": "अमान्य target_date '{target_date}'। YYYY-MM-DD प्रारूप का उपयोग करें।",
        "vi": "target_date không hợp lệ '{target_date}'. Sử dụng định dạng YYYY-MM-DD.",
        "sw": "target_date batili '{target_date}'. Tumia muundo wa YYYY-MM-DD.",
        "tr": "Geçersiz target_date '{target_date}'. YYYY-AA-GG biçimini kullanın.",
    },
    "show_imagery.geometry_error": {
        "en": "Could not load the geometry of the selected AOI.",
        "es": "No se pudo cargar la geometría del área de interés seleccionada.",
        "fr": "Impossible de charger la géométrie de la zone d'intérêt sélectionnée.",
        "pt": "Não foi possível carregar a geometria da área de interesse selecionada.",
        "id": "Tidak dapat memuat geometri AOI yang dipilih.",
        "de": "Die Geometrie des ausgewählten Interessengebiets konnte nicht geladen werden.",
        "it": "Impossibile caricare la geometria dell'area di interesse selezionata.",
        "nl": "Kon de geometrie van het geselecteerde interessegebied niet laden.",
        "ru": "Не удалось загрузить геометрию выбранной зоны интереса.",
        "zh": "无法加载所选兴趣区域的几何数据。",
        "ar": "تعذّر تحميل هندسة المنطقة المحددة.",
        "hi": "चयनित AOI की ज्यामिति लोड नहीं हो सकी।",
        "vi": "Không thể tải hình học của khu vực quan tâm đã chọn.",
        "sw": "Imeshindwa kupakia jiometri ya AOI iliyochaguliwa.",
        "tr": "Seçilen ilgi alanının geometrisi yüklenemedi.",
    },
    "show_imagery.aoi_too_large": {
        "en": "Selected area is too large: {error}",
        "es": "El área seleccionada es demasiado grande: {error}",
        "fr": "La zone sélectionnée est trop grande : {error}",
        "pt": "A área selecionada é muito grande: {error}",
        "id": "Area yang dipilih terlalu besar: {error}",
        "de": "Das ausgewählte Gebiet ist zu groß: {error}",
        "it": "L'area selezionata è troppo grande: {error}",
        "nl": "Het geselecteerde gebied is te groot: {error}",
        "ru": "Выбранная область слишком велика: {error}",
        "zh": "所选区域过大：{error}",
        "ar": "المنطقة المحددة كبيرة جدًا: {error}",
        "hi": "चयनित क्षेत्र बहुत बड़ा है: {error}",
        "vi": "Khu vực đã chọn quá lớn: {error}",
        "sw": "Eneo lililochaguliwa ni kubwa sana: {error}",
        "tr": "Seçilen alan çok büyük: {error}",
    },
    "show_imagery.no_scenes_found": {
        "en": "No Sentinel-2 scenes with under {cloud_cover}% cloud cover found within ±{window_days} days of {target_date}. Suggest to the user: widen the search window (window_days), allow cloudier scenes (max_cloud_cover) or pick a different date — then retry with their choice.",
        "es": "No se encontraron escenas de Sentinel-2 con menos del {cloud_cover}% de cobertura de nubes dentro de ±{window_days} días de {target_date}. Sugiera al usuario: ampliar la ventana de búsqueda (window_days), permitir escenas más nubladas (max_cloud_cover) o elegir una fecha diferente, y luego vuelva a intentarlo con su elección.",
        "fr": "Aucune scène Sentinel-2 avec moins de {cloud_cover} % de couverture nuageuse trouvée dans un intervalle de ±{window_days} jours autour du {target_date}. Suggérez à l'utilisateur : d'élargir la fenêtre de recherche (window_days), d'autoriser des scènes plus nuageuses (max_cloud_cover) ou de choisir une autre date — puis réessayez avec son choix.",
        "pt": "Nenhuma cena Sentinel-2 com menos de {cloud_cover}% de cobertura de nuvens foi encontrada dentro de ±{window_days} dias de {target_date}. Sugira ao usuário: ampliar a janela de busca (window_days), permitir cenas mais nubladas (max_cloud_cover) ou escolher outra data — depois tente novamente com a escolha dele.",
        "id": "Tidak ditemukan citra Sentinel-2 dengan tutupan awan di bawah {cloud_cover}% dalam rentang ±{window_days} hari dari {target_date}. Sarankan kepada pengguna untuk: memperlebar jendela pencarian (window_days), mengizinkan citra yang lebih berawan (max_cloud_cover), atau memilih tanggal lain — lalu coba lagi dengan pilihan mereka.",
        "de": "Es wurden keine Sentinel-2-Szenen mit weniger als {cloud_cover}% Wolkenbedeckung innerhalb von ±{window_days} Tagen um {target_date} gefunden. Schlagen Sie dem Nutzer vor: das Suchfenster zu erweitern (window_days), bewölktere Szenen zuzulassen (max_cloud_cover) oder ein anderes Datum zu wählen — und versuchen Sie es dann mit dessen Wahl erneut.",
        "it": "Non sono state trovate scene Sentinel-2 con copertura nuvolosa inferiore al {cloud_cover}% entro ±{window_days} giorni da {target_date}. Suggerire all'utente di: ampliare la finestra di ricerca (window_days), consentire scene più nuvolose (max_cloud_cover) o scegliere una data diversa, quindi riprovare con la sua scelta.",
        "nl": "Geen Sentinel-2-scènes gevonden met minder dan {cloud_cover}% bewolking binnen ±{window_days} dagen van {target_date}. Stel de gebruiker voor: het zoekvenster te vergroten (window_days), meer bewolkte scènes toe te staan (max_cloud_cover) of een andere datum te kiezen — en probeer het daarna opnieuw met hun keuze.",
        "ru": "Не найдено снимков Sentinel-2 с облачностью менее {cloud_cover}% в пределах ±{window_days} дней от {target_date}. Предложите пользователю: расширить окно поиска (window_days), разрешить более облачные снимки (max_cloud_cover) или выбрать другую дату — затем повторите попытку с его выбором.",
        "zh": "在 {target_date} 前后 ±{window_days} 天内，未找到云量低于 {cloud_cover}% 的 Sentinel-2 影像。请建议用户：扩大搜索窗口（window_days）、允许更多云量的影像（max_cloud_cover），或选择其他日期——然后根据其选择重试。",
        "ar": "لم يتم العثور على مشاهد Sentinel-2 بنسبة غطاء سحابي أقل من {cloud_cover}% ضمن ±{window_days} يومًا من {target_date}. اقترح على المستخدم: توسيع نافذة البحث (window_days)، أو السماح بمشاهد أكثر تلبدًا بالغيوم (max_cloud_cover)، أو اختيار تاريخ آخر — ثم أعد المحاولة باختياره.",
        "hi": "{target_date} के ±{window_days} दिनों के भीतर {cloud_cover}% से कम बादल आवरण वाला कोई Sentinel-2 दृश्य नहीं मिला। उपयोगकर्ता को सुझाव दें: खोज विंडो बढ़ाएँ (window_days), अधिक बादल वाले दृश्यों की अनुमति दें (max_cloud_cover), या कोई अन्य तिथि चुनें — फिर उनकी पसंद के साथ पुनः प्रयास करें।",
        "vi": "Không tìm thấy ảnh Sentinel-2 nào có độ che phủ mây dưới {cloud_cover}% trong khoảng ±{window_days} ngày quanh {target_date}. Hãy gợi ý người dùng: mở rộng khoảng tìm kiếm (window_days), cho phép ảnh nhiều mây hơn (max_cloud_cover) hoặc chọn ngày khác — sau đó thử lại theo lựa chọn của họ.",
        "sw": "Hakuna picha za Sentinel-2 zilizo na kifuniko cha mawingu chini ya {cloud_cover}% zilizopatikana ndani ya siku ±{window_days} za {target_date}. Pendekeza kwa mtumiaji: kupanua dirisha la utafutaji (window_days), kuruhusu picha zenye mawingu zaidi (max_cloud_cover), au kuchagua tarehe tofauti — kisha ujaribu tena kwa chaguo lao.",
        "tr": "{target_date} tarihinin ±{window_days} gün içinde %{cloud_cover}'nin altında bulut örtüsüne sahip Sentinel-2 görüntüsü bulunamadı. Kullanıcıya öner: arama penceresini genişletmesini (window_days), daha bulutlu görüntülere izin vermesini (max_cloud_cover) veya farklı bir tarih seçmesini — ardından seçimiyle yeniden deneyin.",
    },
    "show_imagery.stac_unavailable": {
        "en": "The Sentinel-2 catalog is currently unavailable. Try again later.",
        "es": "El catálogo de Sentinel-2 no está disponible actualmente. Inténtelo de nuevo más tarde.",
        "fr": "Le catalogue Sentinel-2 est actuellement indisponible. Réessayez plus tard.",
        "pt": "O catálogo do Sentinel-2 está atualmente indisponível. Tente novamente mais tarde.",
        "id": "Katalog Sentinel-2 saat ini tidak tersedia. Coba lagi nanti.",
        "de": "Der Sentinel-2-Katalog ist derzeit nicht verfügbar. Versuchen Sie es später erneut.",
        "it": "Il catalogo Sentinel-2 non è attualmente disponibile. Riprovare più tardi.",
        "nl": "De Sentinel-2-catalogus is momenteel niet beschikbaar. Probeer het later opnieuw.",
        "ru": "Каталог Sentinel-2 временно недоступен. Повторите попытку позже.",
        "zh": "Sentinel-2 目录目前不可用，请稍后再试。",
        "ar": "فهرس Sentinel-2 غير متاح حاليًا. حاول مرة أخرى لاحقًا.",
        "hi": "Sentinel-2 कैटलॉग वर्तमान में अनुपलब्ध है। कृपया बाद में पुनः प्रयास करें।",
        "vi": "Danh mục Sentinel-2 hiện không khả dụng. Vui lòng thử lại sau.",
        "sw": "Katalogi ya Sentinel-2 kwa sasa haipatikani. Jaribu tena baadaye.",
        "tr": "Sentinel-2 kataloğu şu anda kullanılamıyor. Daha sonra tekrar deneyin.",
    },
    "show_imagery.unexpected_error": {
        "en": "Something went wrong while building the satellite imagery layer. Please try again later.",
        "es": "Algo salió mal al crear la capa de imágenes satelitales. Por favor, inténtelo de nuevo más tarde.",
        "fr": "Une erreur s'est produite lors de la création de la couche d'imagerie satellite. Veuillez réessayer plus tard.",
        "pt": "Algo deu errado ao criar a camada de imagens de satélite. Tente novamente mais tarde.",
        "id": "Terjadi kesalahan saat membuat layer citra satelit. Silakan coba lagi nanti.",
        "de": "Beim Erstellen der Satellitenbild-Ebene ist ein Fehler aufgetreten. Bitte versuchen Sie es später erneut.",
        "it": "Si è verificato un errore durante la creazione dello strato di immagini satellitari. Riprovare più tardi.",
        "nl": "Er is iets misgegaan bij het maken van de satellietbeeldlaag. Probeer het later opnieuw.",
        "ru": "При создании слоя спутниковых снимков произошла ошибка. Повторите попытку позже.",
        "zh": "构建卫星图像图层时出错，请稍后再试。",
        "ar": "حدث خطأ ما أثناء إنشاء طبقة صور الأقمار الصناعية. يرجى المحاولة مرة أخرى لاحقًا.",
        "hi": "उपग्रह इमेजरी लेयर बनाते समय कुछ गलत हो गया। कृपया बाद में पुनः प्रयास करें।",
        "vi": "Đã xảy ra lỗi khi xây dựng lớp ảnh vệ tinh. Vui lòng thử lại sau.",
        "sw": "Hitilafu ilitokea wakati wa kuunda tabaka la picha za setelaiti. Tafadhali jaribu tena baadaye.",
        "tr": "Uydu görüntü katmanı oluşturulurken bir sorun oluştu. Lütfen daha sonra tekrar deneyin.",
    },
    "show_imagery.success": {
        "en": "Sentinel-2 imagery layer created for {aois}{summary} and shown on the map.",
        "es": "Se creó la capa de imágenes Sentinel-2 para {aois}{summary} y se mostró en el mapa.",
        "fr": "La couche d'imagerie Sentinel-2 a été créée pour {aois}{summary} et affichée sur la carte.",
        "pt": "A camada de imagens Sentinel-2 foi criada para {aois}{summary} e exibida no mapa.",
        "id": "Layer citra Sentinel-2 untuk {aois}{summary} telah dibuat dan ditampilkan di peta.",
        "de": "Sentinel-2-Bildebene für {aois}{summary} erstellt und auf der Karte angezeigt.",
        "it": "Strato di immagini Sentinel-2 creato per {aois}{summary} e mostrato sulla mappa.",
        "nl": "Sentinel-2-beeldlaag gemaakt voor {aois}{summary} en weergegeven op de kaart.",
        "ru": "Слой снимков Sentinel-2 создан для {aois}{summary} и показан на карте.",
        "zh": "已为 {aois}{summary} 创建 Sentinel-2 图像图层，并显示在地图上。",
        "ar": "تم إنشاء طبقة صور Sentinel-2 لـ {aois}{summary} وتم عرضها على الخريطة.",
        "hi": "{aois}{summary} के लिए Sentinel-2 इमेजरी लेयर बनाई गई और मानचित्र पर दिखाई गई।",
        "vi": "Đã tạo lớp ảnh Sentinel-2 cho {aois}{summary} và hiển thị trên bản đồ.",
        "sw": "Tabaka la picha za Sentinel-2 limeundwa kwa {aois}{summary} na kuonyeshwa kwenye ramani.",
        "tr": "{aois}{summary} için Sentinel-2 görüntü katmanı oluşturuldu ve haritada gösterildi.",
    },
    "show_imagery.success_summary": {
        "en": " from {count} scenes acquired between {start} and {end}",
        "es": " a partir de {count} escenas adquiridas entre {start} y {end}",
        "fr": " à partir de {count} scènes acquises entre le {start} et le {end}",
        "pt": " a partir de {count} cenas adquiridas entre {start} e {end}",
        "id": " dari {count} citra yang diperoleh antara {start} dan {end}",
        "de": " aus {count} Szenen, aufgenommen zwischen {start} und {end}",
        "it": " da {count} scene acquisite tra il {start} e il {end}",
        "nl": " van {count} scènes, verkregen tussen {start} en {end}",
        "ru": " из {count} снимков, полученных с {start} по {end}",
        "zh": "，来自 {start} 至 {end} 期间获取的 {count} 张影像",
        "ar": " من {count} مشهد تم الحصول عليها بين {start} و {end}",
        "hi": " {start} और {end} के बीच प्राप्त {count} दृश्यों से",
        "vi": " từ {count} ảnh được thu thập trong khoảng từ {start} đến {end}",
        "sw": " kutoka picha {count} zilizopatikana kati ya {start} na {end}",
        "tr": " {start} ile {end} arasında elde edilen {count} görüntüden",
    },
    "pick_aoi.no_place": {
        "en": "I couldn't identify a place in your request. Which area would you like me to analyze?",
        "es": "No pude identificar un lugar en su solicitud. ¿Qué área le gustaría que analice?",
        "fr": "Je n'ai pas pu identifier de lieu dans votre demande. Quelle zone souhaitez-vous que j'analyse ?",
        "pt": "Não consegui identificar um local em sua solicitação. Qual área você gostaria que eu analisasse?",
        "id": "Saya tidak dapat mengidentifikasi lokasi dalam permintaan Anda. Area mana yang ingin Anda analisis?",
        "de": "Ich konnte in Ihrer Anfrage keinen Ort erkennen. Welches Gebiet möchten Sie analysiert haben?",
        "it": "Non sono riuscito a identificare un luogo nella tua richiesta. Quale area vorresti che analizzassi?",
        "nl": "Ik kon geen locatie in uw verzoek herkennen. Welk gebied wilt u dat ik analyseer?",
        "ru": "Не удалось определить место в вашем запросе. Какую область вы хотите проанализировать?",
        "zh": "我无法在您的请求中识别出地点。您希望我分析哪个区域？",
        "ar": "لم أتمكن من تحديد مكان في طلبك. أي منطقة تريد أن أحللها؟",
        "hi": "मैं आपके अनुरोध में कोई स्थान पहचान नहीं सका। आप चाहते हैं कि मैं किस क्षेत्र का विश्लेषण करूँ?",
        "vi": "Tôi không thể xác định địa điểm trong yêu cầu của bạn. Bạn muốn tôi phân tích khu vực nào?",
        "sw": "Sikuweza kutambua mahali katika ombi lako. Ungependa nichanganue eneo gani?",
        "tr": "İsteğinizde bir yer belirleyemedim. Hangi alanı analiz etmemi istersiniz?",
    },
    "pick_aoi.no_matching_aois": {
        "en": "No matching AOIs were found for your request. Try a broader place name or choose a different subregion type.",
        "es": "No se encontraron áreas de interés que coincidan con su solicitud. Intente con un nombre de lugar más amplio o elija un tipo de subregión diferente.",
        "fr": "Aucune zone d'intérêt correspondante n'a été trouvée pour votre demande. Essayez un nom de lieu plus large ou choisissez un autre type de sous-région.",
        "pt": "Nenhuma área de interesse correspondente foi encontrada para sua solicitação. Tente um nome de local mais amplo ou escolha um tipo de subregião diferente.",
        "id": "Tidak ditemukan AOI yang cocok untuk permintaan Anda. Coba nama tempat yang lebih luas atau pilih jenis subregion yang berbeda.",
        "de": "Für Ihre Anfrage wurden keine passenden Interessengebiete gefunden. Versuchen Sie einen allgemeineren Ortsnamen oder wählen Sie einen anderen Subregionstyp.",
        "it": "Non è stata trovata alcuna area di interesse corrispondente alla richiesta. Provare con un nome di luogo più generico o scegliere un tipo di sottoregione diverso.",
        "nl": "Er zijn geen overeenkomende interessegebieden gevonden voor uw verzoek. Probeer een bredere plaatsnaam of kies een ander subregiotype.",
        "ru": "Подходящие зоны интереса для вашего запроса не найдены. Попробуйте более широкое название места или выберите другой тип подрегиона.",
        "zh": "未找到与您的请求匹配的兴趣区域。请尝试使用更广泛的地名，或选择不同的子区域类型。",
        "ar": "لم يتم العثور على مناطق اهتمام مطابقة لطلبك. جرّب اسم مكان أوسع أو اختر نوع منطقة فرعية مختلف.",
        "hi": "आपके अनुरोध के लिए कोई मिलान AOI नहीं मिला। एक व्यापक स्थान नाम आज़माएँ या एक अलग उपक्षेत्र प्रकार चुनें।",
        "vi": "Không tìm thấy khu vực quan tâm phù hợp với yêu cầu của bạn. Hãy thử một tên địa danh rộng hơn hoặc chọn loại khu vực phụ khác.",
        "sw": "Hakuna AOI zinazolingana zilizopatikana kwa ombi lako. Jaribu jina la mahali pana zaidi au chagua aina tofauti ya subregion.",
        "tr": "İsteğinizle eşleşen ilgi alanı bulunamadı. Daha genel bir yer adı deneyin veya farklı bir alt bölge türü seçin.",
    },
    "pick_aoi.multiple_sources": {
        "en": "Found multiple sources of AOIs, which is not supported. Please select only one source.",
        "es": "Se encontraron múltiples fuentes de áreas de interés, lo cual no es compatible. Seleccione solo una fuente.",
        "fr": "Plusieurs sources de zones d'intérêt ont été trouvées, ce qui n'est pas pris en charge. Veuillez sélectionner une seule source.",
        "pt": "Foram encontradas várias fontes de áreas de interesse, o que não é suportado. Selecione apenas uma fonte.",
        "id": "Ditemukan beberapa sumber AOI, yang tidak didukung. Silakan pilih hanya satu sumber.",
        "de": "Es wurden mehrere Quellen für Interessengebiete gefunden, was nicht unterstützt wird. Bitte wählen Sie nur eine Quelle aus.",
        "it": "Sono state trovate più fonti di aree di interesse, il che non è supportato. Selezionare solo una fonte.",
        "nl": "Er zijn meerdere bronnen van interessegebieden gevonden, wat niet wordt ondersteund. Selecteer slechts één bron.",
        "ru": "Найдено несколько источников зон интереса, что не поддерживается. Пожалуйста, выберите только один источник.",
        "zh": "发现多个兴趣区域来源，这不受支持。请仅选择一个来源。",
        "ar": "تم العثور على مصادر متعددة لمناطق الاهتمام، وهذا غير مدعوم. يرجى اختيار مصدر واحد فقط.",
        "hi": "AOI के कई स्रोत मिले, जो समर्थित नहीं है। कृपया केवल एक स्रोत चुनें।",
        "vi": "Đã tìm thấy nhiều nguồn khu vực quan tâm, điều này không được hỗ trợ. Vui lòng chỉ chọn một nguồn.",
        "sw": "Vyanzo vingi vya AOI vimepatikana, ambavyo havisaidiwi. Tafadhali chagua chanzo kimoja tu.",
        "tr": "Birden fazla ilgi alanı kaynağı bulundu, bu desteklenmiyor. Lütfen yalnızca bir kaynak seçin.",
    },
    "pick_aoi.too_many_subregions": {
        "en": "Found {count} subregions, which is too many to process efficiently. Please narrow down your search by either:\n1. Being more specific with the AOI selection (choose a smaller area)\n2. Being more specific with the subregion query (e.g., 'kbas' instead of 'areas')\nFor optimal performance, please limit results to under {subregion_limit} subregions for KBA, WDPA, and Indigenous Lands, or under {subregion_limit_admin} for other area types.",
        "es": "Se encontraron {count} subregiones, lo cual es demasiado para procesar de forma eficiente. Reduzca su búsqueda de una de estas formas:\n1. Siendo más específico con la selección del área de interés (elija un área más pequeña)\n2. Siendo más específico con la consulta de subregión (por ejemplo, 'kbas' en lugar de 'áreas')\nPara un rendimiento óptimo, limite los resultados a menos de {subregion_limit} subregiones para KBA, WDPA y Tierras Indígenas, o menos de {subregion_limit_admin} para otros tipos de área.",
        "fr": "{count} sous-régions trouvées, ce qui est trop pour un traitement efficace. Veuillez affiner votre recherche en :\n1. Étant plus précis dans la sélection de la zone d'intérêt (choisissez une zone plus petite)\n2. Étant plus précis dans la requête de sous-région (par exemple, « kbas » au lieu de « zones »)\nPour des performances optimales, limitez les résultats à moins de {subregion_limit} sous-régions pour les KBA, WDPA et terres autochtones, ou à moins de {subregion_limit_admin} pour les autres types de zones.",
        "pt": "Foram encontradas {count} subregiões, o que é demais para processar com eficiência. Restrinja sua busca de uma das seguintes formas:\n1. Sendo mais específico na seleção da área de interesse (escolha uma área menor)\n2. Sendo mais específico na consulta de subregião (por exemplo, 'kbas' em vez de 'áreas')\nPara um desempenho ideal, limite os resultados a menos de {subregion_limit} subregiões para KBA, WDPA e Terras Indígenas, ou menos de {subregion_limit_admin} para outros tipos de área.",
        "id": "Ditemukan {count} subregion, yang terlalu banyak untuk diproses secara efisien. Persempit pencarian Anda dengan salah satu cara berikut:\n1. Lebih spesifik dalam pemilihan AOI (pilih area yang lebih kecil)\n2. Lebih spesifik dalam kueri subregion (misalnya, 'kbas' bukan 'areas')\nUntuk performa optimal, batasi hasil hingga kurang dari {subregion_limit} subregion untuk KBA, WDPA, dan Wilayah Adat, atau kurang dari {subregion_limit_admin} untuk jenis area lainnya.",
        "de": "Es wurden {count} Subregionen gefunden, was zu viele für eine effiziente Verarbeitung sind. Bitte grenzen Sie Ihre Suche ein, indem Sie entweder:\n1. Die AOI-Auswahl präzisieren (ein kleineres Gebiet wählen)\n2. Die Subregionsabfrage präzisieren (z. B. 'kbas' statt 'areas')\nFür optimale Leistung begrenzen Sie die Ergebnisse bitte auf unter {subregion_limit} Subregionen für KBA, WDPA und indigene Gebiete, oder unter {subregion_limit_admin} für andere Gebietstypen.",
        "it": "Sono state trovate {count} sottoregioni, un numero troppo elevato per un'elaborazione efficiente. Restringere la ricerca:\n1. Essendo più specifici nella selezione dell'area di interesse (scegliere un'area più piccola)\n2. Essendo più specifici nella query di sottoregione (ad es. 'kbas' invece di 'areas')\nPer prestazioni ottimali, limitare i risultati a meno di {subregion_limit} sottoregioni per KBA, WDPA e terre indigene, o a meno di {subregion_limit_admin} per altri tipi di area.",
        "nl": "Er zijn {count} subregio's gevonden, wat te veel is om efficiënt te verwerken. Verklein uw zoekopdracht door:\n1. Specifieker te zijn met de AOI-selectie (kies een kleiner gebied)\n2. Specifieker te zijn met de subregiovraag (bijv. 'kbas' in plaats van 'areas')\nBeperk voor optimale prestaties de resultaten tot minder dan {subregion_limit} subregio's voor KBA, WDPA en inheemse gebieden, of minder dan {subregion_limit_admin} voor andere gebiedstypen.",
        "ru": "Найдено {count} подрегионов — это слишком много для эффективной обработки. Сузьте поиск, выполнив одно из следующего:\n1. Уточните выбор зоны интереса (выберите меньшую область)\n2. Уточните запрос по подрегиону (например, 'kbas' вместо 'areas')\nДля оптимальной производительности ограничьте результаты до менее {subregion_limit} подрегионов для KBA, WDPA и земель коренных народов, или менее {subregion_limit_admin} для других типов территорий.",
        "zh": "找到 {count} 个子区域，数量过多，无法高效处理。请通过以下方式缩小搜索范围：\n1. 更具体地选择兴趣区域（选择较小的区域）\n2. 更具体地设置子区域查询（例如使用 'kbas' 而不是 'areas'）\n为获得最佳性能，请将 KBA、WDPA 和原住民土地的结果限制在 {subregion_limit} 个子区域以内，其他区域类型限制在 {subregion_limit_admin} 个以内。",
        "ar": "تم العثور على {count} منطقة فرعية، وهذا عدد كبير جدًا لمعالجته بكفاءة. يرجى تضييق نطاق البحث عبر:\n1. تحديد منطقة الاهتمام بمزيد من الدقة (اختر منطقة أصغر)\n2. تحديد استعلام المنطقة الفرعية بمزيد من الدقة (مثل استخدام 'kbas' بدلاً من 'areas')\nللحصول على أفضل أداء، يرجى تحديد النتائج إلى أقل من {subregion_limit} منطقة فرعية لـ KBA و WDPA وأراضي السكان الأصليين، أو أقل من {subregion_limit_admin} لأنواع المناطق الأخرى.",
        "hi": "{count} उपक्षेत्र मिले, जो कुशलता से संसाधित करने के लिए बहुत अधिक हैं। कृपया अपनी खोज को इनमें से किसी एक तरीके से सीमित करें:\n1. AOI चयन में अधिक विशिष्ट बनें (छोटा क्षेत्र चुनें)\n2. उपक्षेत्र क्वेरी में अधिक विशिष्ट बनें (जैसे, 'areas' के बजाय 'kbas')\nसर्वोत्तम प्रदर्शन के लिए, कृपया परिणामों को KBA, WDPA और स्वदेशी भूमि के लिए {subregion_limit} से कम उपक्षेत्रों, या अन्य क्षेत्र प्रकारों के लिए {subregion_limit_admin} से कम तक सीमित करें।",
        "vi": "Đã tìm thấy {count} khu vực phụ, quá nhiều để xử lý hiệu quả. Vui lòng thu hẹp tìm kiếm của bạn bằng cách:\n1. Cụ thể hơn trong việc chọn khu vực quan tâm (chọn khu vực nhỏ hơn)\n2. Cụ thể hơn trong truy vấn khu vực phụ (ví dụ: 'kbas' thay vì 'areas')\nĐể có hiệu suất tối ưu, vui lòng giới hạn kết quả dưới {subregion_limit} khu vực phụ đối với KBA, WDPA và vùng đất bản địa, hoặc dưới {subregion_limit_admin} đối với các loại khu vực khác.",
        "sw": "Subregion {count} zimepatikana, ambazo ni nyingi sana kuchakatwa kwa ufanisi. Tafadhali punguza utafutaji wako kwa mojawapo ya njia hizi:\n1. Kuwa mahususi zaidi katika uchaguzi wa AOI (chagua eneo dogo zaidi)\n2. Kuwa mahususi zaidi katika swali la subregion (mfano, 'kbas' badala ya 'areas')\nKwa utendaji bora, tafadhali punguza matokeo hadi chini ya subregion {subregion_limit} kwa KBA, WDPA, na Ardhi za Wenyeji, au chini ya {subregion_limit_admin} kwa aina nyingine za maeneo.",
        "tr": "{count} alt bölge bulundu, bu verimli işlemek için çok fazla. Lütfen aramanızı şu şekillerden biriyle daraltın:\n1. İlgi alanı seçiminde daha spesifik olun (daha küçük bir alan seçin)\n2. Alt bölge sorgusunda daha spesifik olun (örneğin 'areas' yerine 'kbas')\nEn iyi performans için lütfen sonuçları KBA, WDPA ve Yerli Toprakları için {subregion_limit} alt bölgenin altında, diğer alan türleri için {subregion_limit_admin} altında sınırlayın.",
    },
    "pick_aoi.duplicate_names": {
        "en": "I found multiple locations named '{short_name}' in different countries. Please tell me which one you meant:\n\n{candidate_names}\n\nWhich location are you looking for?",
        "es": "Encontré varios lugares llamados '{short_name}' en diferentes países. Indíqueme cuál quiso decir:\n\n{candidate_names}\n\n¿Qué ubicación está buscando?",
        "fr": "J'ai trouvé plusieurs lieux nommés « {short_name} » dans différents pays. Merci de préciser lequel vous vouliez dire :\n\n{candidate_names}\n\nQuel emplacement recherchez-vous ?",
        "pt": "Encontrei vários locais chamados '{short_name}' em países diferentes. Diga-me qual deles você quis dizer:\n\n{candidate_names}\n\nQual local você está procurando?",
        "id": "Saya menemukan beberapa lokasi bernama '{short_name}' di negara yang berbeda. Beri tahu saya mana yang Anda maksud:\n\n{candidate_names}\n\nLokasi mana yang Anda cari?",
        "de": "Ich habe mehrere Orte namens '{short_name}' in verschiedenen Ländern gefunden. Bitte teilen Sie mir mit, welchen Sie meinten:\n\n{candidate_names}\n\nWelchen Ort suchen Sie?",
        "it": "Ho trovato più località chiamate '{short_name}' in paesi diversi. Indicami quale intendevi:\n\n{candidate_names}\n\nQuale località stai cercando?",
        "nl": "Ik heb meerdere locaties genaamd '{short_name}' in verschillende landen gevonden. Laat me weten welke u bedoelde:\n\n{candidate_names}\n\nWelke locatie zoekt u?",
        "ru": "Я нашёл несколько мест с названием '{short_name}' в разных странах. Пожалуйста, уточните, какое вы имели в виду:\n\n{candidate_names}\n\nКакое место вы ищете?",
        "zh": "我在不同国家找到了多个名为“{short_name}”的地点。请告诉我您指的是哪一个：\n\n{candidate_names}\n\n您要查找的是哪个地点？",
        "ar": "وجدت عدة مواقع تسمى '{short_name}' في بلدان مختلفة. يرجى إخباري بأيها تقصد:\n\n{candidate_names}\n\nأي موقع تبحث عنه؟",
        "hi": "मुझे अलग-अलग देशों में '{short_name}' नाम के कई स्थान मिले। कृपया मुझे बताएं कि आपका मतलब किससे था:\n\n{candidate_names}\n\nआप किस स्थान की खोज कर रहे हैं?",
        "vi": "Tôi tìm thấy nhiều địa điểm có tên '{short_name}' ở các quốc gia khác nhau. Vui lòng cho tôi biết bạn muốn nói đến địa điểm nào:\n\n{candidate_names}\n\nBạn đang tìm địa điểm nào?",
        "sw": "Nimepata maeneo kadhaa yenye jina '{short_name}' katika nchi tofauti. Tafadhali niambie ni lipi ulilomaanisha:\n\n{candidate_names}\n\nUnatafuta eneo lipi?",
        "tr": "Farklı ülkelerde '{short_name}' adında birden fazla yer buldum. Lütfen hangisini kastettiğinizi söyleyin:\n\n{candidate_names}\n\nHangi konumu arıyorsunuz?",
    },
    "pick_aoi.global_subregion_country_only": {
        "en": "Global queries only support subregion='country'. Please set subregion='country' to compare across all countries.",
        "es": "Las consultas globales solo admiten subregion='country'. Establezca subregion='country' para comparar entre todos los países.",
        "fr": "Les requêtes globales ne prennent en charge que subregion='country'. Définissez subregion='country' pour comparer tous les pays.",
        "pt": "As consultas globais só suportam subregion='country'. Defina subregion='country' para comparar entre todos os países.",
        "id": "Kueri global hanya mendukung subregion='country'. Setel subregion='country' untuk membandingkan seluruh negara.",
        "de": "Globale Anfragen unterstützen nur subregion='country'. Bitte setzen Sie subregion='country', um alle Länder zu vergleichen.",
        "it": "Le query globali supportano solo subregion='country'. Impostare subregion='country' per confrontare tutti i paesi.",
        "nl": "Globale query's ondersteunen alleen subregion='country'. Stel subregion='country' in om alle landen te vergelijken.",
        "ru": "Глобальные запросы поддерживают только subregion='country'. Установите subregion='country', чтобы сравнить все страны.",
        "zh": "全球查询仅支持 subregion='country'。请设置 subregion='country' 以比较所有国家。",
        "ar": "الاستعلامات العالمية تدعم فقط subregion='country'. يرجى ضبط subregion='country' للمقارنة بين جميع البلدان.",
        "hi": "वैश्विक क्वेरी केवल subregion='country' का समर्थन करती हैं। सभी देशों की तुलना करने के लिए कृपया subregion='country' सेट करें।",
        "vi": "Truy vấn toàn cầu chỉ hỗ trợ subregion='country'. Vui lòng đặt subregion='country' để so sánh giữa tất cả các quốc gia.",
        "sw": "Maswali ya kimataifa yanasaidia tu subregion='country'. Tafadhali weka subregion='country' ili kulinganisha nchi zote.",
        "tr": "Genel sorgular yalnızca subregion='country' değerini destekler. Tüm ülkeleri karşılaştırmak için lütfen subregion='country' olarak ayarlayın.",
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
