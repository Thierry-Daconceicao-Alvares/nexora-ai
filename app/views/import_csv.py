"""Import several requests from a CSV file."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import state
import ui
from client import ApiError

TEMPLATE = (
    "external_ref,department,supplier_id,item_category,item_code,description,quantity,"
    "unit_price,currency,justification,delivery_date,is_capex,attachments\n"
    "PR-2026-01001,Maintenance,SUP-0002,spare_parts,MRO-BRG-6205,"
    "Ball bearings 6205-2RS for line 3,20,8.40,EUR,Preventive maintenance of line 3,"
    "2026-12-01,false,quote:q1.pdf\n"
)


def render() -> None:
    st.title("Import a file")
    st.markdown(
        "One request per row. Each row is checked on its own: valid rows are submitted, "
        "the others are listed with what to fix. A row sent twice is recognised and not "
        "submitted again."
    )
    st.download_button(
        "Download the template",
        TEMPLATE,
        file_name="nexora-requests-template.csv",
        mime="text/csv",
    )
    upload = st.file_uploader("CSV file", type=["csv"], max_upload_size=1)
    if upload is None:
        return
    if not st.button("Submit the rows", type="primary"):
        return
    try:
        result = state.call(
            "POST",
            "/requests/import",
            files={"file": (upload.name, upload.getvalue(), "text/csv")},
        )
    except ApiError as error:
        state.show_error(error)
        return
    st.success(
        f"{result['created']} submitted, {result['already_submitted']} already submitted, "
        f"{result['refused']} refused, out of {ui.plural(result['rows'], 'row')}."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Line": r["line"],
                    "Reference": r["external_ref"],
                    "Result": r["status"].replace("_", " "),
                    "Status": r.get("request_status", ""),
                    "What to fix": "; ".join(
                        f"{e.get('field') or 'row'}: {e['message']}" for e in r.get("errors", [])
                    ),
                }
                for r in result["results"]
            ]
        ),
        hide_index=True,
        width="stretch",
    )
