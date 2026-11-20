import asyncio
from datetime import date
from pathlib import Path
from typing import Annotated, Dict, Optional, Sequence, Union

import pandas as pd
from langchain.tools import InjectedState
from langchain_core.messages import ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langgraph.types import Command
from shapely import box

from src.agent.datasets.config import (
    CANDIDATE_DATASET_REQUIRED_COLUMNS,
    DATASETS,
    RETIRED_DATASET_IDS,
)
from src.agent.datasets.dates import revise_date_range
from src.agent.datasets.tiles import get_tile_services_for_dataset
from src.agent.i18n import t
from src.agent.language import (
    DEFAULT_LANGUAGE,
    language_name,
    resolve_language,
)
from src.agent.llms import resilient_structured_output
from src.agent.subagents.pick_dataset.prompts import DATASET_SELECTOR_PROMPT
from src.agent.subagents.pick_dataset.schema import (
    DatasetOption,
    DatasetParameter,
    DatasetSelectionResponse,
    DatasetSelectionResult,
)
from src.agent.subagents.progress import emit_progress
from src.agent.tool_spec import ToolCategory, ToolSpec, bound_availability
from src.agent.tools.send_nudge import NUDGE_ALREADY_SET_NOTE
from src.shared.config import SharedSettings
from src.shared.decisions import Answer as DecisionAnswer
from src.shared.decisions import DecisionError, decide
from src.shared.decisions import Question as DecisionQuestion
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _drop_excluded_datasets(
    candidate_datasets: pd.DataFrame, excluded: frozenset[str]
) -> pd.DataFrame:
    """Remove datasets the current agent profile excludes from the candidate
    set, so a hidden dataset is never offered to the selector."""
    if not excluded:
        return candidate_datasets
    return candidate_datasets[
        ~candidate_datasets["dataset_name"].isin(excluded)
    ]


data_dir = Path("data")

retriever_cache = None


def _catalog_by_id() -> dict[int, dict]:
    """Catalog datasets keyed by dataset_id, for doc-id lookups."""
    return {ds["dataset_id"]: ds for ds in DATASETS}


def _document_dataset_id(doc) -> Optional[int]:
    """The dataset_id a retrieved document points at, or None if its id is
    not an integer (a malformed or foreign document in the index)."""
    try:
        return int(doc.id)
    except (TypeError, ValueError):
        return None


def _log_index_catalog_skew(index: InMemoryVectorStore) -> None:
    """Compare the loaded index against the catalog and report any skew.

    The index is a build artifact of the catalog (see
    src/ingest/embed_datasets.py), but it is published separately, as an S3
    object the pods sync into `data/`. A catalog change that ships without a
    rebuilt index leaves the two out of step: documents for removed datasets
    keep coming back from retrieval, and datasets added since the last build
    can never be retrieved. Both are silent faults, so name them once at load.
    """
    catalog_ids = set(_catalog_by_id())
    doc_ids = set()
    for doc_id in getattr(index, "store", {}):
        try:
            doc_ids.add(int(doc_id))
        except (TypeError, ValueError):
            doc_ids.add(doc_id)

    removed = doc_ids - catalog_ids
    missing = catalog_ids - doc_ids
    # A retired id explains itself: the index predates the removal of that
    # dataset. An indexed id the catalog has never held does not, so name the
    # two apart.
    retired = removed & RETIRED_DATASET_IDS
    unknown = removed - RETIRED_DATASET_IDS
    if removed or missing:
        logger.error(
            "Dataset embeddings index %s is out of step with the catalog. "
            "Indexed but retired from the catalog: %s. Indexed and unknown "
            "to the catalog: %s. In the catalog but not indexed: %s. Rebuild "
            "the index from the catalog (src/ingest/embed_datasets.py), "
            "publish it under a NEW version name, and point "
            "DATASET_EMBEDDINGS_DB at that name.",
            SharedSettings.dataset_embeddings_db,
            sorted(retired, key=str) or "none",
            sorted(unknown, key=str) or "none",
            sorted(missing, key=str) or "none",
        )
    else:
        logger.info(
            "Dataset embeddings index %s matches the catalog (%s datasets).",
            SharedSettings.dataset_embeddings_db,
            len(catalog_ids),
        )


async def _get_retriever():
    global retriever_cache
    if retriever_cache is None:
        logger.debug("Loading retriever for the first time...")
        embeddings = GoogleGenerativeAIEmbeddings(
            model=SharedSettings.dataset_embeddings_model,
            task_type=SharedSettings.dataset_embeddings_task_type,
        )
        index = InMemoryVectorStore.load(
            data_dir / SharedSettings.dataset_embeddings_db,
            embedding=embeddings,
        )
        _log_index_catalog_skew(index)
        retriever_cache = index.as_retriever(
            search_type="similarity", search_kwargs={"k": 5}
        )
    return retriever_cache


# The most candidates that a retrieval for several queries gives: the same
# number as one retrieval, so the selection prompt does not grow.
MAX_CANDIDATES = 5


def _interleave(lists: Sequence[list], limit: int) -> list:
    """The items of ``lists`` taken in turn (first of each list, then the
    second of each, ...), without duplicates, at most ``limit``."""
    merged: list = []
    for rank in range(max((len(items) for items in lists), default=0)):
        for items in lists:
            if rank < len(items) and items[rank] not in merged:
                merged.append(items[rank])
    return merged[:limit]


async def rag_candidate_datasets(query: Union[str, Sequence[str]], k=3):
    """The catalog datasets that the index retrieves for ``query``.

    With several queries (the user's message and the agent's request), each
    query is retrieved and the results are interleaved, so each query keeps
    its best matches: the user's words can omit a dataset of an earlier
    turn that only the agent's request names."""
    queries = [query] if isinstance(query, str) else list(query)
    logger.debug(f"Retrieving candidate datasets for queries: {queries!r}")
    candidate_datasets = []
    stale_doc_ids = []
    retriever = await _get_retriever()
    results = await asyncio.gather(*(retriever.ainvoke(q) for q in queries))
    if len(results) == 1:
        match_documents = list(results[0])
    else:
        ranked_ids = _interleave(
            [[doc.id for doc in docs] for docs in results], MAX_CANDIDATES
        )
        by_id = {doc.id: doc for docs in results for doc in docs}
        match_documents = [by_id[doc_id] for doc_id in ranked_ids]
    catalog = _catalog_by_id()
    for doc in match_documents:
        dataset_id = _document_dataset_id(doc)
        dataset = None if dataset_id is None else catalog.get(dataset_id)
        if dataset is None:
            # The index still holds a dataset the catalog has dropped. Skip
            # it and keep the valid candidates: a stale index must degrade
            # the shortlist, not fail the turn.
            stale_doc_ids.append(doc.id)
            continue
        candidate_datasets.append(dataset)

    if stale_doc_ids:
        logger.warning(
            "Skipped %s retrieved document(s) with no matching catalog "
            "dataset: %s. Index %s holds datasets the catalog no longer "
            "has; rebuild and republish it "
            "(src/ingest/embed_datasets.py). Catalog ids: %s.",
            len(stale_doc_ids),
            stale_doc_ids,
            SharedSettings.dataset_embeddings_db,
            sorted(catalog),
        )

    logger.debug(f"Found {len(candidate_datasets)} candidate datasets.")
    names = [ds["dataset_name"] for ds in candidate_datasets]
    emit_progress(
        "pick_dataset",
        "shortlist",
        f"Shortlisted {len(names)} candidate(s): {', '.join(names)}",
    )
    return pd.DataFrame(candidate_datasets)


SELECTION_RULES = """- Only choose a dataset if it can usefully answer ALL parts of the user's question.
- If no candidate can do that, return dataset_id as null and explain in the reason field what data we do have and why it falls short.
- Use the selection hints above — they are the primary signal for which dataset fits.
- Select a context layer when its description matches the query (pre-filtered to the AOI).
- Select parameters only when relevant; use only values listed in the dataset.
- If the user specifies a date range or time granularity (e.g. monthly, a specific year, daily alerts), only select a dataset if it genuinely supports that.
- Pick the most granular dataset/context layer/parameters that matches the query.
- Keep explanations concise. Do not reference dataset IDs."""

# The rules when the selection reads the user's own message
# (`selection_query`). A user's message often has parts that no dataset gives:
# why something happened, what the figures are for ("for NDC tracking"), a
# policy. With the first rule above, the selection then offered a choice of
# datasets for "Why did Brazil lose so much primary forest in 2016?". The
# agent explains those parts; the selection picks the data.
USER_MESSAGE_SELECTION_RULES = SELECTION_RULES.replace(
    "- Only choose a dataset if it can usefully answer ALL parts of the "
    "user's question.",
    "- Choose the dataset that gives the data the request needs. A part of "
    "the request that no dataset gives (why something happened, what the "
    "figures are for, a policy, a commodity) is not a reason to choose no "
    "dataset: the agent explains that part.",
) + (
    # The tree cover loss hints make primary forest the default for "general
    # forest loss" in the humid tropics. With the user's message, the
    # selection applied it to plain "tree cover loss in Antioquia in 2023"
    # (45 of 178 tree cover loss attempts, BENCHMARK 2026-11-17).
    # "Deforestation" is loss of natural forest, so the hints' default stays
    # for it: without a layer, "How much deforestation occurred in Brazil in
    # 2023?" got all tree cover loss (BENCHMARK 2026-11-17, `3a9075df`).
    "\n- Select a context layer only when the request names it, asks for "
    "a kind of forest (primary, intact, natural, plantation) or asks about "
    "deforestation. For deforestation, use the context layer that the "
    'dataset hints give. A plain "tree cover loss" or "forest loss" '
    "request gets no context layer, also in the humid tropics."
)
assert USER_MESSAGE_SELECTION_RULES != SELECTION_RULES


def _format_selection_hints(candidate_datasets: pd.DataFrame) -> str:
    lines = []
    for _, row in candidate_datasets.iterrows():
        hints = (row.get("selection_hints") or "").strip()
        if hints:
            lines.append(f"{row['dataset_name']}:\n{hints}")
    return "\n\n".join(lines) if lines else ""


def _format_layer(layer: dict) -> str:
    """One layer as `name (title): description`, parts omitted when absent."""
    line = layer["name"]
    if layer.get("title"):
        line += f" ({layer['title']})"
    if layer.get("description"):
        line += f": {layer['description']}"
    return line


def _format_layer_options(candidate_datasets: pd.DataFrame) -> str:
    """The choices for `selected_layer`: each multi-layer candidate's layers
    by name, title and description. Tile URLs are left out — they carry no
    selection signal."""
    blocks = []
    for _, row in candidate_datasets.iterrows():
        layers = row.get("layers")
        if not isinstance(layers, list) or len(layers) <= 1:
            continue
        lines = "\n".join(f"- {_format_layer(layer)}" for layer in layers)
        blocks.append(f"{row['dataset_name']}:\n{lines}")
    return "\n\n".join(blocks) if blocks else "None"


async def _select_with_llm(
    query: str,
    candidate_datasets: pd.DataFrame,
    removed_df: Optional[str],
    language: str,
    rules: str = SELECTION_RULES,
) -> DatasetSelectionResponse:
    """The selection model: the fallback when the decision call fails."""
    DATASET_SELECTION_PROMPT = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                DATASET_SELECTOR_PROMPT.format(
                    language=language_name(language)
                ),
            ),
            (
                "user",
                """## When to prefer each candidate dataset

{selection_hints}

## Rules

{rules}

## Candidate datasets

{candidate_datasets}

## Map layers (for selected_layer)

{layer_options}

## User query

{user_query}

## Removed contextual layers

{removed_layers}

## Reminder: when to prefer each candidate dataset

{selection_hints}

## Reminder: rules

{rules}
""",
            ),
        ]
    )

    logger.debug("Invoking dataset selection chain...")
    dataset_selection_chain = (
        DATASET_SELECTION_PROMPT
        | resilient_structured_output(DatasetSelectionResponse)
    ).with_config(run_name="select_dataset")

    selection_hints = _format_selection_hints(candidate_datasets)
    layer_options = _format_layer_options(candidate_datasets)

    return await dataset_selection_chain.ainvoke(
        {
            "candidate_datasets": candidate_datasets[
                CANDIDATE_DATASET_REQUIRED_COLUMNS
            ].to_csv(index=False),
            "user_query": query,
            "removed_layers": removed_df,
            "selection_hints": selection_hints,
            "layer_options": layer_options,
            "rules": rules,
        }
    )


def latest_user_message(messages) -> Optional[str]:
    """The text of the latest human message, or None."""
    for message in reversed(messages or []):
        if getattr(message, "type", None) != "human":
            continue
        content = message.content
        if isinstance(content, list):
            content = " ".join(
                part if isinstance(part, str) else str(part.get("text", ""))
                for part in content
                if isinstance(part, (str, dict))
            )
        text = str(content or "").strip()
        return text or None
    return None


def selection_query(query: str, user_message: Optional[str]) -> str:
    """The query that the selection model reads.

    The orchestrator often rewrites the request into a dataset phrase ("tree
    cover loss by driver (fire)") and drops what the user asked for ("has
    fire-driven loss gone down since 2019"). The selection then offers a
    choice of datasets where the user's words fit one. So the user's message
    comes first, and the orchestrator's query is context for what the message
    does not say, for example a place or a dataset of an earlier turn.

    A message can ask for more than one dataset ("compare tree cover loss
    and fire alerts"); the orchestrator then calls pick_dataset one time for
    each. The agent's request says which part to select in this call.
    """
    if not user_message or user_message.strip() == query.strip():
        return query
    return (
        f"{user_message}\n\nThe agent's request for this selection: {query}\n"
        "Use the message above for what the user wants. Use the agent's "
        "request for what the message does not say, for example a place or "
        "a dataset named in an earlier turn. When the message asks for more "
        "than one dataset, select the one for the part that the agent's "
        "request names."
    )


# The decision model (DECISION_PROVIDER: Gemini Decision 1, or jev) picks
# the dataset. The request structure was tuned offline on jev
# (~/bench-runs/jev-picker/eval.py; PR #841 for the earlier work):
# - jev sees every dataset in the profile, not the RAG shortlist.
# - Each dataset is one option: its catalog `decision_key` as the key and
#   its short `decision_card` as the text. The long LLM text is worse.
# - Short neutral instructions. LLM rules such as "only choose a dataset if
#   it answers ALL parts" make jev decline valid requests.
# - The dataset is asked alone. A second call asks for the context layer,
#   map layer and parameters of the chosen dataset only: asking them in the
#   same call changes the dataset answer.
# - A low top probability asks the user (the dataset-choice nudge): jev
#   seldom picks "none" when one dataset matches in part.
APP_CONTEXT = (
    "The user asks questions about environmental data for places on a "
    "map. Each question needs one dataset. A question about a topic asks "
    "for the dataset that measures it."
)
DATASET_INSTRUCTIONS = (
    "Which dataset answers the user's request best? Choose 'none' only "
    "when none of the datasets measures what the request is about."
)
NO_DATASET = "none"
NO_DATASET_TEXT = "None of these datasets measures what the request is about"
# The same rule as USER_MESSAGE_SELECTION_RULES gives the selection LLM. The
# catalog hints make primary forest the default for "general forest loss". A
# decision call that reads them applied it to plain "tree cover loss" in
# 12 of 51 trials (BENCHMARK 2026-draft-5, PR #922); the rule fixed all of
# them on 111 tree cover loss questions in an offline test.
CONTEXT_INSTRUCTIONS = (
    "Which forest or land type does the user's request ask the {dataset} "
    "data to be limited to? Limit it to a forest type only when the "
    "request names it, asks for a kind of forest (primary, intact, natural, "
    "plantation) or asks about deforestation. For deforestation, use the "
    "layer that its description says is the default. A plain "
    '"tree cover loss" or "forest loss" request has no limit, also in the '
    "humid tropics."
)
NO_CONTEXT = "all"
NO_CONTEXT_TEXT = "No limit: all of the area"
LAYER_INSTRUCTIONS = (
    "Which map layer of {dataset} matches the focus of the user's request "
    "best?"
)
PARAMETER_INSTRUCTIONS = (
    "Which value of '{parameter}' does the user's request ask for, for "
    "{dataset}? {description}"
)
NO_PARAMETER = "default"
NO_PARAMETER_TEXT = "The request names no value"
# Below this top probability the user chooses from the closest datasets.
# 0.5 was the best value on the dev set; higher values ask on too many
# requests that have one right answer.
ASK_BELOW = 0.5
# A suggestion needs at least this probability.
SUGGESTION_THRESHOLD = 0.05
MAX_SUGGESTIONS = 3


class NoCandidateDatasets(RuntimeError):
    """The fallback selection had no candidate datasets to choose from."""


def _text(value) -> str:
    """A catalog text field; a missing one is None or NaN in the frame."""
    return value.strip() if isinstance(value, str) else ""


def _first_sentence(value) -> str:
    text = _text(value)
    end = text.find(". ")
    return text if end == -1 else text[: end + 1]


def _decision_key(row) -> str:
    return _text(row.get("decision_key")) or str(row["dataset_id"])


def _decision_card(row) -> str:
    return (
        _text(row.get("decision_card"))
        or _text(row.get("selection_hints"))
        or row["dataset_name"]
    )


def profile_datasets() -> pd.DataFrame:
    """Every dataset the current agent profile offers."""
    return _drop_excluded_datasets(
        pd.DataFrame(DATASETS), bound_availability().excluded_datasets
    ).reset_index(drop=True)


def _dataset_state(
    query: str, start_date: Optional[str], end_date: Optional[str]
) -> str:
    text = f"{APP_CONTEXT}\n\nUser request: {query}"
    if start_date or end_date:
        text += (
            f"\nRequested period: {start_date or 'open'} to "
            f"{end_date or 'open'}"
        )
    return text


def _dataset_question(candidate_datasets: pd.DataFrame) -> DecisionQuestion:
    return DecisionQuestion(
        DATASET_INSTRUCTIONS,
        {
            **{
                _decision_key(row): _decision_card(row)
                for _, row in candidate_datasets.iterrows()
            },
            NO_DATASET: NO_DATASET_TEXT,
        },
    )


def _option_questions(row: pd.Series) -> dict[str, DecisionQuestion]:
    """The context layer, map layer and parameters of one dataset."""
    name = row["dataset_name"]
    questions: dict[str, DecisionQuestion] = {}
    context_layers = row.get("context_layers")
    if isinstance(context_layers, list) and context_layers:
        questions["context"] = DecisionQuestion(
            CONTEXT_INSTRUCTIONS.format(dataset=name),
            {
                **{
                    layer["value"]: layer.get("description") or layer["value"]
                    for layer in context_layers
                },
                NO_CONTEXT: NO_CONTEXT_TEXT,
            },
        )
    layers = row.get("layers")
    if isinstance(layers, list) and len(layers) > 1:
        questions["layer"] = DecisionQuestion(
            LAYER_INSTRUCTIONS.format(dataset=name),
            {layer["name"]: _format_layer(layer) for layer in layers},
        )
    parameters = row.get("parameters")
    for param in parameters if isinstance(parameters, list) else []:
        values = param.get("values") or []
        if not values:
            continue
        questions[f"param_{param['name']}"] = DecisionQuestion(
            PARAMETER_INSTRUCTIONS.format(
                dataset=name,
                parameter=param["name"],
                description=param.get("description") or "",
            ).strip(),
            {
                **{str(v): str(v) for v in values},
                NO_PARAMETER: NO_PARAMETER_TEXT,
            },
        )
    return questions


def _option_from_answers(
    row: pd.Series, answers: dict[str, DecisionAnswer], reason: str
) -> DatasetOption:
    context = answers.get("context")
    layer = answers.get("layer")
    parameters = []
    raw_parameters = row.get("parameters")
    for param in raw_parameters if isinstance(raw_parameters, list) else []:
        answer = answers.get(f"param_{param['name']}")
        if answer is None or answer.choice == NO_PARAMETER:
            continue
        value = next(
            (v for v in param["values"] if str(v) == answer.choice), None
        )
        if value is not None:
            parameters.append(
                DatasetParameter(
                    name=param["name"],
                    description=param.get("description") or "",
                    values=[value],
                )
            )
    return DatasetOption(
        dataset_id=int(row["dataset_id"]),
        context_layer=(
            context.choice
            if context and context.choice != NO_CONTEXT
            else None
        ),
        selected_layer=layer.choice if layer else None,
        parameters=parameters or None,
        start_date=None,
        end_date=None,
        reason=reason,
    )


def _suggestion(row: pd.Series) -> DatasetOption:
    return _option_from_answers(
        row, {}, _first_sentence(row.get("description")) or row["dataset_name"]
    )


async def _select_with_decisions(
    query: str,
    candidate_datasets: pd.DataFrame,
    start_date: Optional[str],
    end_date: Optional[str],
) -> DatasetSelectionResponse:
    """The dataset from one decision call, then its options from a second one.

    Raises:
        DecisionError: When a call fails or returns no dataset answer.
    """
    state = _dataset_state(query, start_date, end_date)
    answers = await decide(
        state, {"dataset": _dataset_question(candidate_datasets)}
    )
    dataset = answers.get("dataset")
    if dataset is None:
        raise DecisionError("no answer for the dataset question")
    rows = {
        _decision_key(row): row for _, row in candidate_datasets.iterrows()
    }
    logger.info(
        "DATASET-SELECTOR: decision (%s) %s (p=%.3f), probabilities %s",
        SharedSettings.decision_provider,
        dataset.choice,
        dataset.probability,
        dataset.probabilities,
    )

    if dataset.choice != NO_DATASET and dataset.probability >= ASK_BELOW:
        row = rows[dataset.choice]
        options = _option_questions(row)
        option_answers = await decide(state, options) if options else {}
        reason = (
            f"Best match for the request among the {len(rows)} datasets, "
            f"with probability {dataset.probability:.2f}."
        )
        return DatasetSelectionResponse(
            selected_dataset=_option_from_answers(row, option_answers, reason),
            suggested_datasets=None,
            reason=reason,
        )

    # No clear match: offer the datasets that came closest, if any.
    ranked = sorted(
        (
            (p, key)
            for key, p in dataset.probabilities.items()
            if key in rows and p >= SUGGESTION_THRESHOLD
        ),
        reverse=True,
    )[:MAX_SUGGESTIONS]
    suggestions = [_suggestion(rows[key]) for _, key in ranked]
    if dataset.choice == NO_DATASET:
        reason = (
            "None of the datasets measures what the request asks about "
            "directly."
        )
    else:
        reason = "More than one dataset could answer the request."
    return DatasetSelectionResponse(
        suggested_datasets=suggestions or None,
        reason=reason,
    )


async def select_best_dataset(
    query: str,
    candidate_datasets: pd.DataFrame,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    aoi_selection=None,
    language: str = DEFAULT_LANGUAGE,
    rules: str = SELECTION_RULES,
    retrieval_query: Union[str, Sequence[str], None] = None,
) -> DatasetSelectionResponse:
    """Pick the dataset with the decision model (DECISION_PROVIDER).

    `query` is the text the selection reads (`selection_query`) and
    `candidate_datasets` are all datasets of the profile. Context layers
    outside the AOI are removed first. When a decision call fails, the RAG
    shortlist (searched with `retrieval_query`, default `query`) and the
    selection LLM (with `rules`) pick instead.

    Raises:
        NoCandidateDatasets: When the fallback finds no candidates.
    """
    if aoi_selection is not None:
        filtered_layers, _ = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )
        candidate_datasets["context_layers"] = filtered_layers

    try:
        return await _select_with_decisions(
            query, candidate_datasets, start_date, end_date
        )
    except DecisionError as exc:
        logger.warning(
            "DATASET-SELECTOR: decision call failed, using the selection "
            "model: %s",
            exc,
        )
    return await _select_with_rag_and_llm(
        query, retrieval_query or query, aoi_selection, language, rules
    )


async def _select_with_rag_and_llm(
    query: str,
    retrieval_query: Union[str, Sequence[str]],
    aoi_selection,
    language: str,
    rules: str,
) -> DatasetSelectionResponse:
    """The earlier selection: RAG shortlist, then the selection LLM."""
    candidate_datasets = await rag_candidate_datasets(retrieval_query, k=5)
    # Drop datasets the current agent profile (feature flag) excludes, so
    # they can never be selected under a flag that hides them.
    if not candidate_datasets.empty:
        candidate_datasets = _drop_excluded_datasets(
            candidate_datasets, bound_availability().excluded_datasets
        )
    if candidate_datasets.empty:
        # Nothing retrieved survived the catalog lookup or the profile
        # exclusions. The cause is in the logs.
        logger.error(
            "No candidate datasets for query %r (index %s). Every "
            "retrieved document was skipped.",
            query,
            SharedSettings.dataset_embeddings_db,
        )
        raise NoCandidateDatasets(query)
    if aoi_selection is None:
        removed_df = None
    else:
        filtered_layers, removed_layers = get_filtered_contextual_layers(
            candidate_datasets["context_layers"], aoi_selection
        )
        candidate_datasets["context_layers"] = filtered_layers
        removed_df = removed_layers.to_csv(index=False)
    return await _select_with_llm(
        query, candidate_datasets, removed_df, language, rules
    )


class DatasetSelector:
    """Dataset-selection subagent: resolves a request to the best dataset.

    Used as a tool by the orchestrator via `pick_dataset`. The orchestrator
    passes the user's request; this subagent picks the dataset and its
    context layer and parameters with the decision model (RAG and the
    selection LLM, driven by DATASET_SELECTOR_PROMPT, are the fallback), and
    clamps the date range to the dataset's real coverage.
    """

    async def resolve(
        self,
        query: str,
        aoi_selection=None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        language: str = DEFAULT_LANGUAGE,
        user_message: Optional[str] = None,
    ) -> Command:
        """Resolve a request to the best dataset and update state.

        `user_message` is the user's latest message. When it is given, the
        retrieval uses it and `query`, and the selection reads it before
        `query` (`selection_query`)."""
        logger.info("DATASET-SELECTOR: resolving query")
        selection_text = selection_query(query, user_message)

        # Every dataset of the profile is a candidate. The decision model
        # picks the dataset and its options; RAG and the selection LLM are
        # the fallback.
        candidate_datasets = profile_datasets()
        try:
            selection_result = await select_best_dataset(
                selection_text,
                candidate_datasets,
                start_date,
                end_date,
                aoi_selection,
                language=language,
                rules=(
                    USER_MESSAGE_SELECTION_RULES
                    if selection_text != query
                    else SELECTION_RULES
                ),
                retrieval_query=(
                    [user_message, query]
                    if selection_text != query and user_message
                    else query
                ),
            )
        except NoCandidateDatasets:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            await t(
                                "pick_dataset.retrieval_unavailable", language
                            ),
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )

        if selection_result.selected_dataset is None:
            if selection_result.suggested_datasets:
                name_by_id = {
                    ds["dataset_id"]: ds["dataset_name"] for ds in DATASETS
                }
                reasons = "\n".join(
                    f"- {name_by_id.get(o.dataset_id, str(o.dataset_id))}: {o.reason}"
                    for o in selection_result.suggested_datasets
                )
                intro = await t(
                    "pick_dataset.no_single_match",
                    language,
                    reason=selection_result.reason,
                )
                options_header = await t(
                    "pick_dataset.closest_options_header", language
                )
                tool_message = (
                    f"{intro}\n\n{options_header}\n{reasons}"
                    f"{NUDGE_ALREADY_SET_NOTE}"
                )
                return Command(
                    update={
                        "nudge": {
                            "type": "dataset_choice",
                            "options": [
                                name_by_id[o.dataset_id]
                                for o in selection_result.suggested_datasets
                            ],
                            "data": [
                                {
                                    **o.model_dump(),
                                    "dataset_name": name_by_id[o.dataset_id],
                                }
                                for o in selection_result.suggested_datasets
                            ],
                        },
                        "messages": [
                            ToolMessage(
                                tool_message,
                                tool_call_id=tool_call_id,
                                status="success",
                                response_metadata={
                                    "msg_type": "human_feedback"
                                },
                            )
                        ],
                    }
                )
            else:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                await t(
                                    "pick_dataset.no_match",
                                    language,
                                    reason=selection_result.reason,
                                ),
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )

        option = selection_result.selected_dataset

        logger.debug(
            f"Selected dataset ID: {option.dataset_id}. "
            f"context_layer={option.context_layer!r} (type={type(option.context_layer).__name__}). "
            f"selected_layer={option.selected_layer!r}. "
            f"Reason: {option.reason}"
        )

        selected_row = candidate_datasets[
            candidate_datasets.dataset_id == option.dataset_id
        ].iloc[0]

        effective_start_date, effective_end_date, _ = await revise_date_range(
            start_date,
            end_date,
            selected_row.dataset_id,
            option.context_layer,
        )
        dataset_tile_url, context_layers, layers = (
            get_tile_services_for_dataset(
                option,
                selected_row,
                effective_start_date,
                effective_end_date,
            )
        )

        dataset_result = DatasetSelectionResult(
            dataset_id=selected_row.dataset_id,
            dataset_name=selected_row.dataset_name,
            context_layer=option.context_layer,
            selected_layer=option.selected_layer,
            parameters=option.parameters,
            start_date=effective_start_date,
            end_date=effective_end_date,
            reason=option.reason,
            tile_url=dataset_tile_url,
            layers=layers,
            analytics_api_endpoint=selected_row.analytics_api_endpoint,
            description=selected_row.description,
            prompt_instructions=selected_row.prompt_instructions,
            methodology=selected_row.methodology,
            cautions=selected_row.cautions,
            function_usage_notes=selected_row.function_usage_notes,
            citation=selected_row.citation,
            content_date=selected_row.content_date,
            selection_hints=selected_row.selection_hints,
            code_instructions=selected_row.code_instructions,
            presentation_instructions=selected_row.presentation_instructions,
            context_layers=context_layers,
        )

        layer = dataset_result.context_layer
        emit_progress(
            "pick_dataset",
            "selected",
            f"Selected dataset: {dataset_result.dataset_name}"
            + (f" (context layer: {layer})" if layer else ""),
        )

        # The map layer(s) this dataset renders, and which one is on the map.
        # Without this the agent only ever sees the dataset name and its
        # (inventory-flavoured) prose, and narrates that there is no map layer
        # even as the frontend paints the one that was selected.
        layers = [layer.model_dump() for layer in dataset_result.layers]
        if layers:
            available_layers = "".join(
                f"\n      - {_format_layer(layer)}" for layer in layers
            )
            displayed = next(
                (
                    layer
                    for layer in layers
                    if layer["name"] == dataset_result.selected_layer
                ),
                layers[0],
            )
            displayed_layer = _format_layer(displayed)
        else:
            available_layers = displayed_layer = "none"

        tool_message = f"""# About the selection
    Selected dataset name: {dataset_result.dataset_name}
    Selected context layer: {dataset_result.context_layer}
    Map layers available: {available_layers}
    Map layer displayed: {displayed_layer}
    Reasoning for selection: {dataset_result.reason}

    # Additional dataset information

    ## Description

    {dataset_result.description}

    ## Function usage notes

    {dataset_result.function_usage_notes}

    ## Usage cautions

    {dataset_result.cautions}

    ## Content date

    {dataset_result.content_date}
    """

        if dataset_result.presentation_instructions:
            tool_message += f"""
    ## Presentation instructions

    {dataset_result.presentation_instructions}
    """

        logger.debug(f"Pick dataset tool message: {tool_message}")

        return Command(
            update={
                "dataset": dataset_result.model_dump(),
                "nudge": {"type": "", "options": []},
                "messages": [
                    ToolMessage(tool_message, tool_call_id=tool_call_id)
                ],
            },
        )


@tool("pick_dataset")
async def pick_dataset(
    query: str,
    state: Annotated[Dict, InjectedState],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    tool_call_id: Annotated[Optional[str], InjectedToolCallId] = None,
) -> Command:
    """Pick the dataset, context layer and date range that best answer the
    user's request — a dataset-selection subagent.

    Pass the user's request as `query`. The subagent retrieves candidate
    datasets, picks the best match, resolves the context layer/parameters and
    clamps the date range to what the dataset actually covers.

    - Dataset-only requests (e.g. "pick tcl by driver", "use tree cover loss
      by driver"): an AOI is NOT required — do not ask for a country/region,
      and do not call pick_aoi / pull_data / generate_insights unless the user
      asks for more. Briefly confirm the selection.
    - Re-pick: call this again before pull_data whenever the user changes the
      dataset, the context layer (drivers, land cover change, time dynamics,
      etc.) or parameters.
    - Optional start_date/end_date (YYYY-MM-DD) narrow the range; if they
      don't exactly match the dataset, the closest valid range is used.
    """
    # state["language"] should already carry the turn's resolved language
    # (see src.agent.language.resolve_language, set in chat.py); detecting
    # from `query` here is a fallback for callers that invoke this subagent
    # standalone, without going through that per-turn resolution.
    language = (
        state.get("language")
        or await resolve_language(query=query)
        or DEFAULT_LANGUAGE
    )
    return await DatasetSelector().resolve(
        query,
        aoi_selection=state.get("aoi_selection"),
        start_date=start_date,
        end_date=end_date,
        tool_call_id=tool_call_id,
        language=language,
        # The selection reads the user's own words (selection_query).
        user_message=latest_user_message(state.get("messages")),
    )


def get_filtered_contextual_layers(
    context_layers: pd.Series, aoi_selection
) -> pd.Series:
    """
    Filter contextual layer by spatial extent. All AOIs in selection intersect the layer
    for valid comparison.

    Returns both filtered down layers per dataset, and a set of all removed layers
    to inform the agent.
    """

    aoi_bboxes = [box(*aoi["bbox"]) for aoi in aoi_selection["aois"]]
    removed_layers = []
    extent_filter_reason = (
        "Selected area(s) of interest outside extent of layer."
    )

    def _filter_context_layers(
        context_layers: list[dict],
    ) -> Union[pd.Series, pd.DataFrame]:
        if context_layers is None:
            return None

        filtered_layers = []
        for layer in context_layers:
            extent = layer.get("extent")

            # no extent defined, assume global
            if not extent:
                filtered_layers.append(layer)
            else:
                extent_geom = box(*extent)
                if all(
                    [
                        aoi_bbox.intersects(extent_geom)
                        for aoi_bbox in aoi_bboxes
                    ]
                ):
                    filtered_layers.append(layer)
                else:
                    removed_layers.append(
                        {"layer_name": layer, "reason": extent_filter_reason}
                    )
        return filtered_layers

    filtered_layers = context_layers.apply(_filter_context_layers)

    # get df of unique contextual layers
    removed_df = pd.DataFrame(removed_layers).drop_duplicates(
        subset="layer_name"
    )

    return filtered_layers, removed_df


def get_dates_for_dataset(
    selection_result, selected_row, start_date, end_date
) -> tuple[str, str]:
    """Resolve missing dates from the selected dataset's own coverage."""
    dataset_start_date = selected_row.get("start_date")
    dataset_end_date = selected_row.get("end_date") or str(date.today())

    resolved_start_date = start_date or dataset_start_date
    resolved_end_date = end_date or dataset_end_date

    logger.debug(
        "Resolved dates for dataset %s (%s): start=%s end=%s",
        selection_result.dataset_id,
        selected_row.get("dataset_name"),
        resolved_start_date,
        resolved_end_date,
    )

    return resolved_start_date, resolved_end_date


SPEC = ToolSpec(
    tool=pick_dataset,
    category=ToolCategory.SUBAGENT,
    prompt_fragment="- pick_dataset(query): dataset-selection subagent. Picks the dataset, context layer and date range that best answer the request. May return no dataset if none is a good fit — in that case relay its explanation and closest alternatives to the user; do not proceed to pull_data. Call it again whenever the user changes the dataset, context layer or parameters.",
)
