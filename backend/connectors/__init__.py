"""AgentForge data connectors — business-data ingestion layer.

Public surface (pinned by docs/INTERFACES.md; see interface.md for the full
contract that backend/app consumes):

    from connectors import (
        ParsedDataset,
        parse_csv,             # file object | bytes | path | text -> ParsedDataset
        parse_pasted_table,    # pasted text (Sheets/Excel style) -> ParsedDataset
        load_sample,           # sample_id -> (ParsedDataset, data_dictionary)
        SAMPLE_IDS,            # ("saas_churn", "ecommerce_sales",
        #                       "support_tickets", "marketing_spend")
        SAMPLE_META,           # {sample_id: {name, description, row_count, story}}
        DATA_DICTIONARIES,     # {sample_id: {column: {type, units, description}}}
    )

Typical use from the FastAPI layer (cwd=backend, so ``import connectors``):

    parsed = parse_csv(payload_bytes, filename=upload.filename)
    return UploadResponse(**parsed.to_dict())
"""

from __future__ import annotations

from .csv_parser import (
    MAX_COLUMNS,
    PREVIEW_ROWS,
    DTYPES_VOCABULARY,
    ParsedDataset,
    detect_encoding,
    parse_csv,
    parse_text_table,
    sniff_delimiter,
)
from .paste_parser import clean_pasted_text, detect_paste_delimiter, parse_pasted_table
from .samples import (
    DATA_DICTIONARIES,
    SAMPLE_IDS,
    SAMPLE_META,
    load_sample,
    samples_dir,
)

__version__ = "1.0.0"

__all__ = [
    "ParsedDataset",
    "parse_csv",
    "parse_pasted_table",
    "load_sample",
    "SAMPLE_IDS",
    "SAMPLE_META",
    "DATA_DICTIONARIES",
    "samples_dir",
    "parse_text_table",
    "sniff_delimiter",
    "detect_encoding",
    "clean_pasted_text",
    "detect_paste_delimiter",
    "MAX_COLUMNS",
    "PREVIEW_ROWS",
    "DTYPES_VOCABULARY",
    "__version__",
]
