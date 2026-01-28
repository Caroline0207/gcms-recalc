import io
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="GC-MS Data Cleaning", layout="wide")

REQUIRED_COLS = ["Peak", "RT", "Area", "Height", "Name", "Formula", "Species", "Score"]

st.title("GC-MS Data Cleaning 🫧")
ANALYSIS_APP_URL = "https://gcms-analyze-gm8cqhckpwmym6caacqkqn.streamlit.app/"

with st.sidebar:
    st.markdown("### Navigation")
    st.link_button("🧪 Go to Analysis Web", ANALYSIS_APP_URL)

st.caption(
    "Paste an Excel table (tab-separated) below. "
    "The app will calculate Area sums, exclude Air/Si/No-data peaks, "
    "recalculate area percentages, and validate that Recalc % sums to 100."
)

# ---------- UI ----------
calc = st.button("Calculate", type="primary")

raw = st.text_area(
    "Paste your Excel table here (including header row):",
    height=260,
    placeholder="Paste tab-separated data copied directly from Excel…",
)

# ---------- Helpers ----------
def _coerce_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "", regex=False).str.strip()
    s = s.replace({"": np.nan, "None": np.nan, "nan": np.nan})
    return pd.to_numeric(s, errors="coerce")

def parse_tsv(text: str) -> pd.DataFrame:
    if not text or not text.strip():
        raise ValueError("Input is empty. Please paste a table copied from Excel.")

    try:
        df = pd.read_csv(io.StringIO(text.strip()), sep="\t", dtype=str, engine="python")
    except Exception as e:
        raise ValueError(f"Failed to parse TSV input: {e}")

    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}\n"
            f"Detected columns: {list(df.columns)}"
        )

    for c in df.columns:
        df[c] = df[c].astype(str).replace("nan", "").str.strip()

    df["Peak"] = _coerce_number(df["Peak"]).astype("Int64")
    df["RT"] = _coerce_number(df["RT"])
    df["Area"] = _coerce_number(df["Area"])
    df["Height"] = _coerce_number(df["Height"])
    df["Score"] = _coerce_number(df["Score"])

    return df

def classify_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    formula = out["Formula"].fillna("").astype(str).str.strip()
    peak = out["Peak"]

    category = pd.Series(["Relevant"] * len(out), index=out.index)

    air_mask = peak == 1
    si_mask = (~air_mask) & formula.str.contains("si", case=False, na=False)
    nodata_mask = (~air_mask) & (~si_mask) & (formula == "")

    category.loc[nodata_mask] = "No data"
    category.loc[si_mask] = "Si peak"
    category.loc[air_mask] = "Air peak"

    out["Category"] = category
    return out

def compute(df: pd.DataFrame):
    df = classify_rows(df)

    area_sum = df["Area"].sum(skipna=True)
    air_sum = df.loc[df["Category"] == "Air peak", "Area"].sum(skipna=True)
    si_sum = df.loc[df["Category"] == "Si peak", "Area"].sum(skipna=True)
    nodata_sum = df.loc[df["Category"] == "No data", "Area"].sum(skipna=True)

    recalc_sum = area_sum - (air_sum + si_sum + nodata_sum)

    df["Area %"] = np.nan
    if area_sum > 0:
        df["Area %"] = (df["Area"] / area_sum) * 100

    df["Recalc %"] = np.nan
    if recalc_sum > 0:
        rel_mask = df["Category"] == "Relevant"
        df.loc[rel_mask, "Recalc %"] = (df.loc[rel_mask, "Area"] / recalc_sum) * 100
        recalc_total = df.loc[rel_mask, "Recalc %"].sum(skipna=True)
        diff_100 = recalc_total - 100
    else:
        recalc_total = np.nan
        diff_100 = np.nan

    summary = {
        "Area sum": area_sum,
        "Air peak sum": air_sum,
        "Si peak sum": si_sum,
        "No data sum": nodata_sum,
        "Recalc sum": recalc_sum,
        "Recalc % total": recalc_total,
        "Difference from 100%": diff_100,
    }

    return df, summary

def copy_to_clipboard_button(text: str, label: str = "Copy to clipboard"):
    """
    Renders a button that copies `text` to clipboard using browser JS.
    """
    safe_text = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    html = f"""
    <button style="
        padding:0.45rem 0.8rem;
        border-radius:0.5rem;
        border:1px solid rgba(49, 51, 63, 0.2);
        background:white;
        cursor:pointer;
        font-size:0.9rem;
    " onclick="navigator.clipboard.writeText(`{safe_text}`).then(() => {{
        const el = document.getElementById('copy-status');
        if (el) {{
            el.textContent = '✅ Copied!';
            setTimeout(() => el.textContent = '', 1500);
        }}
    }});">
        {label}
    </button>
    <span id="copy-status" style="margin-left:0.6rem;font-size:0.9rem;"></span>
    """
    components.html(html, height=40)


# ---------- Main ----------
if calc:
    try:
        df = parse_tsv(raw)
        df_calc, summary = compute(df)

        st.subheader("Summary")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Area sum", f"{summary['Area sum']:,.2f}")
        c2.metric("Air peak sum", f"{summary['Air peak sum']:,.2f}")
        c3.metric("Si peak sum", f"{summary['Si peak sum']:,.2f}")
        c4.metric("No data sum", f"{summary['No data sum']:,.2f}")
        c5.metric("Recalc sum", f"{summary['Recalc sum']:,.2f}")

        if not np.isnan(summary["Recalc % total"]):
            status = "✅ OK" if abs(summary["Difference from 100%"]) < 0.01 else "⚠️ Check"
            st.info(
                f"Recalc % total (Relevant only): "
                f"{summary['Recalc % total']:.6f}%  \n"
                f"Difference from 100%: {summary['Difference from 100%']:.6f} ({status})"
            )
        else:
            st.warning(
                "Recalc % could not be computed because recalc sum is ≤ 0. "
                "This usually means Air / Si / No-data peaks dominate the Area."
            )

        st.divider()
        st.subheader("Cleaned Output Table")

        show_excluded = st.toggle(
            "Show excluded peaks (Air / Si / No data)",
            value=False,
        )

        out_cols = [
            "Peak", "RT", "Area", "Height",
            "Area %", "Recalc %",
            "Name", "Formula", "Species", "Score", "Category"
        ]
        out = df_calc[out_cols].copy()

        if not show_excluded:
            out = out[out["Category"] == "Relevant"]

        out = out.sort_values(by="Recalc %", ascending=False, na_position="last")

        display_cols = [
            "Peak", "RT", "Area", "Height",
            "Area %", "Recalc %",
            "Name", "Formula", "Species", "Score"
        ]

        display_df = out[display_cols].copy()
        for c in ["RT", "Area", "Height", "Score"]:
            display_df[c] = display_df[c].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}"
            )
        for c in ["Area %", "Recalc %"]:
            display_df[c] = display_df[c].apply(
                lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}"
            )

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        # ---------- Copy section ----------
        st.subheader("Copy")

        tsv_text = out[display_cols].to_csv(index=False, sep="\t")
        copy_to_clipboard_button(
            tsv_text,
            label="📋 Copy table (TSV, incl. header)"
        )

        # Optional download
        with st.expander("Optional: Download file"):
            csv = out[display_cols].to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                csv,
                file_name="gcms_recalc_cleaned.csv",
                mime="text/csv",
            )

    except Exception as e:
        st.error(str(e))
