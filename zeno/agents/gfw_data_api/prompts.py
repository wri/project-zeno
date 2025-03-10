from typing import List

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
    prompt = f"Select a data table from the GFW data api to query, based on the user's question: {query} \n and using this csv defininig the tables: {DATATABLES}. Return one row from the csv as the answer. The answer should be formatted as 'table,description'."
    return prompt


def prep_field_selection_prompt(
    query: str, table_slug: str, fields: str, gadm_level: int, gadm_ids: List[str]
) -> List[str]:

    prompt = f"""
You are Zeno - a helpful AI assistant.
You are helping a user query the Global Forest Watch data API. The user has asked the following question: {query}. You will construct a SQL query to retrieve the requested data. You query should select one or more fields from the following list of fields: {fields}. Your query should be formatted as a SQL SELECT statement with appropriate filters, grouping and ordering. Condsider the following example template: \n 
\n
SELECT {gadm_level}, {{query_fields}} \n
FROM {table_slug} \n
WHERE  {gadm_level} IN ({gadm_ids}) \n
    AND {{filtering_fields}} \n
GROUP BY {{grouping_field}} \n
ORDER BY {{ordering_field}} \n
\n
Replace the placeholders {{query_fields}}, {{filtering_fields}}, {{grouping_field}} and {{ordering_field}} with the appropriate fields from the list of fields provided, in order to craft a query which responds to the user's question. Note that the placeholder {{query_fields}} can be replaced with one or more fields, separated by commas, and can also be an opperation apprproiate for the field's type, such as the SQL SUM() operation for numeric fields. The placeholder {{filtering_fields}} can be replaced with one or more filtering conditions, such as 'umd_tree_cover_density_2000__threshold' > 30, separated by AND \n
Return a string formatted SQL statement with no additional text, or prompt the user for more information if needed.
"""

    return prompt
