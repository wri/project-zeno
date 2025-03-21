from typing import List, Optional

from datetime import datetime

current_date = datetime.now().strftime("%d %b %Y")

GFW_DATA_API_PROMPT = f"""
You are Zeno - a helpful AI assistant.
Use the provided tools to prepare and execute an API request against the Global Forest Watch data API.
If the user doesn't provide enough information to call the tools, such as a place name or date range,
ask follow up questions without picking a default.\n
Current date: {current_date}.
"""

DATATABLES = """
table,description
summary,Provides a static summary of total tree cover extent (2000-2010); tree cover loss (2001-2023) and tree cover gain (2000-2020)
change,Provides annual deforestation and carbon data
daily_alerts,Provides daily forest disturbance in near-real-time using integrated alerts from three alerting systems
"""


def prep_datatables_selection_prompt(user_query: str) -> str:
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query conservation and biodiversity data from the Global Forest Watch data API. \n
Select a data table from the GFW data api to query, based on the user's question and a csv defining the available data tables. \n
User's question: {user_query} \n
\n
CSV with available data tables: {DATATABLES} \n"""
    return prompt


def prep_field_selection_prompt(user_query: str, fields: List[str]) -> str:
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
Select one or more fields from the list of fields provided, based on the user's question and a csv defining the available fields to query. \n
User's question: {user_query} \n
CSV with available fields: {fields} \n
Return one or more rows from the csv as the answer, where each row is formatted as 'name,data_type', and each row is separated by a newline \\n character. Do not include any additional text
    """
    return prompt


def prep_api_sql_query_prompt(
    user_query: str,
    fields_to_query: str,
    gadm_level: int,
    location_filter: Optional[str] = "",
) -> List[str]:

    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You will construct a SQL query to retrieve the requested data. You will be provided with the user's question and a list of fields to query, as pairs of field name and data type and a template for the SQL query with some information pre-filled. Do your best not to alter the existing elements of this template. \n

User's question: {user_query} \n
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
Make sure to enclose each of the query fields with double quotes (") in order to ensure that the SQL query is properly formatted. If there is anything you are unsure about you can say that. The user will be able to correct the query. \n
Return a string formatted SQL statement with no additional text, or you can prompt the user for more information, if needed.
"""

    return prompt


def prep_sql_query_explanation_prompt(user_query: str, sql_query: str):
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed a SQL query which will be run against the GFW data API and you will now explain how you constructed this query to the user.\n
Be sure to explain: \n
- Why each field in the SELECT statement was chosen and what any additional operations, such as the SUM operation, are performed. \n
- Why the filtering condition was chose, especially for filters NOT relating to gadm_ids. \n
- Why any grouping operation was performed. \n
Be sure to explain each part in such a way that a user that is familiar with the GFW data and API, but not very familiar with SQL syntax would understand. \n
Do not add anything beyond the explanation itself, do not offer to further elaborate \n
User's question: {user_query} \n
SQL Query to explain: {sql_query} \n
"""
    return prompt


def prep_query_results_explanation_prompt(
    user_query: str, query_results: dict, location_info: dict
):
    prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed and run a SQL query against the GFW data API and you will now explain the results of this query to the user and how it answers their question.\n
The query results will reference GADM IDs (iso, adm1 and adm2), use the location information provided to better explain the results. \n
User's question: {user_query} \n
Query results to explain: {query_results} \n
Location info: {location_info} \n
"""
    return prompt


def prep_modify_sql_query_prompt(
    user_query: str,
    sql_query: str,
    error: Optional[str] = "",
    modification: Optional[str] = "",
) -> str:
    if not error and not modification:
        raise ValueError("One of error or modification must be provided")
    if error:
        prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed a SQL query which has been run against the GFW data API, but the API returned an error. Consider the user's original question, the generated SQL query and the error message returned from the API, and return an updated SQL query that will not result in errors when run. Do not return anything else other than the SQL query itself. \n
User question: {user_query} \n
SQL Query: {sql_query} \n
API Error: {error} \n
"""
    else:
        prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed a SQL query which will be run against the GFW data API, but the user has requested a modification to the query. Consider the user's original question, the generated SQL query and user's requested modification, and return an updated SQL query that reflects the user's requested modifications. Do not return anything else other than the SQL query itself. \n
User question: {user_query} \n
SQL Query: {sql_query} \n
User requested modification: {modification} \n
"""
    return prompt


def prep_sql_query_modified_explanation_prompt(
    user_query: str,
    original_sql_query: str,
    modified_sql_query: str,
    error: Optional[str] = "",
    modification: Optional[str] = "",
):

    if not error and not modification:
        raise ValueError("One of error or modification must be provided")
    if error:
        prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed a SQL query which has been run against the GFW data API, but the API returned an error. You have modified this query to avoid further errors. Consider the user's original question, the original SQL query, the modified SQL query and the error message returned from the API and explain the modifications to the user, and how the modifications will avoid any further error. Do not return anything beyond this explanation, do not offer to further explain. \n
User question: {user_query} \n
Original SQL Query: {original_sql_query} \n
Modified SQL Query: {modified_sql_query} \n
API Error: {error} \n
"""
    else:
        prompt = f"""
You are Zeno, a helpful AI assistant helping users query environmental conservation and biodiversity data from the Global Forest Watch data API. \n
You have constructed a SQL query which will be run against the GFW data API, but the user has requested a modification to the query. Consider the user's original question, the original SQL query, the modified query, the user's requested modification, and explain the modifications to the user, and how the modifications reflect the user's requested modifications. Do not return anythign beyond this explanation, do not offer to further explain. \n
User question: {user_query} \n
Original SQL Query: {original_sql_query} \n
Modified SQL Query: {modified_sql_query} \n
User requested modification: {modification} \n
"""
    return prompt
