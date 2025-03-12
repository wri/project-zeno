from typing import List, Optional

GFW_DATA_API_PROMPT = """
You are Zeno - a helpful AI assistant.
Use the provided tools to prepare and execute API requests against the Global Forest Watch data API.
If the user doesn't provide enough information to call the tools like a place name or date range,
ask follow up questions without picking a default.
"""

DATATABLES = """
table,description
summary,Provides a static summary of total tree cover extent (2000-2010); tree cover loss (2001-2023) and tree cover gain (2000-2020)
change,Provides annual deforestation and carbon data
daily_alerts,Provides daily forest disturbance in near-real-time using integrated alerts from three alerting systems
"""


def prep_datatables_selection_prompt(query: str) -> str:
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query conservation and biodiversity data from the Global Forest Watch data API. \n
Select a data table from the GFW data api to query, based on the user's question and a csv defining the available data tables. \n
User's question: {query} \n
\n
CSV with available data tables: {DATATABLES} \n"""
    return prompt


def prep_field_selection_prompt(query: str, fields: List[str]) -> str:
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
Select one or more fields from the list of fields provided, based on the user's question and a csv defining the available fields to query. \n
User's question: {query} \n
CSV with available fields: {fields} \n
Return one or more rows from the csv as the answer, where each row is formatted as 'name,data_type', and each row is separated by a newline \\n character. Do not include any additional text
    """
    return prompt


def prep_api_sql_query_prompt(
    query: str,
    fields_to_query: str,
    gadm_level: int,
    location_filter: Optional[str] = "",
) -> List[str]:

    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You will construct a SQL query to retrieve the requested data. You will be provided with the user's question and a list of fields to query, as pairs of field name and data type and a template for the SQL query with some information pre-filled. Do your best not to alter the existing elements of this template. \n

User's question: {query} \n
Fields to query: \n{fields_to_query} \n
Template: \n

SELECT {gadm_level}, {{query_fields}} \n
FROM data \n
WHERE  ({location_filter}) AND {{filtering_fields}} \n
GROUP BY {{grouping_field}} \n
ORDER BY {{ordering_field}} \n
\n
Replace the placeholder {{query_fields}} with the fields from the list of the fields provided with any additional relevant SQL operation, appropriate for the field's data type, such as SUM() for numeric fields. \n
Replace the placeholder {{filtering_fields}} with one or more filtering conditions, such as 'umd_tree_cover_density_2000__threshold' > 30, separated by AND. \n
Replace the placeholder {{grouping_field}} with the field to group the data by, if appropriate. Otherwise you may choose to omit this portion of the query. \n
Replace the placeholder {{ordering_field}} with the field to order the data by, if appropriate. Otherwise you may choose to omit this portion of the query. \n
Make sure to enclose each of the query fields with double quotes (") in order to ensure that the SQL query is properly formatted. \n
Return a string formatted SQL statement with no additional text, or you can prompt the user for more information, if needed.
"""

    return prompt


# SELECT adm1, SUM(umd_tree_cover_density__threshold) as total_tree_cover_density, SUM(umd_tree_cover_density_2000__threshold) as total_tree_cover_density_2000

# FROM data

# WHERE adm1 IN ('BRA.1_1', 'BRA.2_1', 'BRA.3_1', 'BRA.4_1', 'BRA.5_1', 'BRA.6_1', 'BRA.7_1', 'BRA.8_1', 'BRA.9_1', 'BRA.10_1', 'BRA.11_1', 'BRA.12_1', 'BRA.13_1', 'BRA.14_1', 'BRA.15_1', 'BRA.16_1', 'BRA.17_1', 'BRA.18_1', 'BRA.19_1', 'BRA.20_1', 'BRA.21_1', 'BRA.22_1', 'BRA.23_1', 'BRA.24_1', 'BRA.25_1', 'BRA.26_1', 'BRA.27_1') AND umd_tree_cover_density__threshold > 0 AND umd_tree_cover_density_2000__threshold > 0

# GROUP BY adm1

# ORDER BY total_tree_cover_density DESC
