import io
import pandas as pd
import numpy as np
import streamlit as st

st.set_page_config(page_title="GC/LC Peak Recalc Area%", layout="wide")

SAMPLE = """Peak\tRT\tArea\tHeight\tType\tSaturated\tWidth\tFWHM\tBest\tID Source\tName\tFormula\tSpecies\tm/z\tScore
1\t1.873\t5335421.44\t410135.89\t\t\t0.191\t0.159\t\t\t\t\t\t\t
2\t1.941\t176904225.9\t3794823.58\t\t\t1.344\t0.835\tTRUE\tLibSearch\tFuran, 2,3-dihydro-\tC4H6O\tor hydrazinecarboxamide or oxygen\t\t80.67
3\t3.957\t7483195.32\t293489.54\t\t\t1.117\t0.397\t\t\t\t\t\t\t
"""

REQUIRED_COLS = ["Peak", "RT", "Area", "Height", "Name", "Formula", "Species", "Score"]

st.title("GC/LC Peak Table Recalc Area% Calculator")

colA, colB, colC = st.columns([1, 1, 2], vertical_alignment="bottom")
with colA:
    calc = st.button("Calculate", type="primary", use_container_width=True)
with colB:
    clear = st.button("Clear", use_container_width=True)
with colC:
    load_sample = st.button("Load sample", use_container_width=False)

if "raw" not in st.session_state:
    st.session_state.raw = ""

if load_sample:
    st.session_state.raw = SAMPLE

if clear:
    st.session_state.raw = ""

raw = st.text_area(
    "엑셀 표(헤더 포함)를 그대로 붙여넣으세요 (TSV / tab-separated).",
    value=st.session_state.raw,
    height=260,
    placeholder="여기에 붙여넣기…",
)
st.session_state.raw = raw

def _coerce_number(series: pd.Series) -> pd.Series:
    # remove commas, spaces; coerce to float
    s = series.astype(str).str.replace(",", "", regex=False).str.strip()
    s = s.replace({"": np.nan, "None": np.nan, "nan": np.nan})
    return pd.to_numeric(s, errors="coerce")

def parse_tsv(text: str) -> pd.DataFrame:
    if not text or not text.strip():
        raise ValueError("입력 텍스트가 비어있어요. 엑셀에서 표를 복사해 붙여넣어 주세요.")
    # Read as TSV, allow ragged rows
    try:
        df = pd.read_csv(io.StringIO(text.strip()), sep="\t", dtype=str, engine="python")
    except Exception as e:
        raise ValueError(f"TSV 파싱에 실패했어요: {e}")

    # strip column names
    df.columns = [c.strip() for c in df.columns]
    # ensure required columns exist
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없어요: {missing}\n현재 컬럼: {list(df.columns)}")

    # trim whitespace in all cells
    for c in df.columns:
        df[c] = df[c].astype(str).replace("nan", "").str.strip()

    # numeric coercions
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

    # priority: Air (Peak==1) > Si > No data > Relevant
    cat = pd.Series(["Relevant"] * len(out), index=out.index)

    air_mask = (peak == 1)
    si_mask = (~air_mask) & (formula.str.contains("si", case=False, na=False))
    nodata_mask = (~air_mask) & (~si_mask) & (formula.eq(""))

    cat.loc[nodata_mask] = "No data"
    cat.loc[si_mask] = "Si peak"
    cat.loc[air_mask] = "Air peak"

    out["Category"] = cat
    return out

def compute(df: pd.DataFrame):
    df = classify_rows(df)

    area_sum = df["Area"].sum(skipna=True)

    air_sum = df.loc[df["Category"] == "Air peak", "Area"].sum(skipna=True)
    si_sum = df.loc[df["Category"] == "Si peak", "Area"].sum(skipna=True)
    nodata_sum = df.loc[df["Category"] == "No data", "Area"].sum(skipna=True)

    recalc_sum = area_sum - (air_sum + si_sum + nodata_sum)

    # Area %
    if area_sum and area_sum > 0:
        df["Area %"] = (df["Area"] / area_sum) * 100
    else:
        df["Area %"] = np.nan

    # Recalc % for Relevant only
    df["Recalc %"] = np.nan
    if recalc_sum and recalc_sum > 0:
        rel_mask = df["Category"] == "Relevant"
        df.loc[rel_mask, "Recalc %"] = (df.loc[rel_mask, "Area"] / recalc_sum) * 100

        recalc_total = df.loc[rel_mask, "Recalc %"].sum(skipna=True)
        diff_100 = recalc_total - 100.0
    else:
        recalc_total = np.nan
        diff_100 = np.nan

    summary = {
        "Area sum": area_sum,
        "Air peak sum": air_sum,
        "Si peak sum": si_sum,
        "No data sum": nodata_sum,
        "recalc sum": recalc_sum,
        "Recalc % total (Relevant only)": recalc_total,
        "Difference from 100%": diff_100,
    }

    return df, summary

def fmt(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        return f"{x:,.2f}"
    except Exception:
        return str(x)

def fmt_pct(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:,.2f}%"

if calc:
    try:
        df = parse_tsv(raw)
        df_calc, summary = compute(df)

        # Summary row
        st.subheader("Summary")

        m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
        m1.metric("Area sum", fmt(summary["Area sum"]))
        m2.metric("Air peak sum", fmt(summary["Air peak sum"]))
        m3.metric("Si peak sum", fmt(summary["Si peak sum"]))
        m4.metric("No data sum", fmt(summary["No data sum"]))
        m5.metric("recalc sum", fmt(summary["recalc sum"]))

        recalc_total = summary["Recalc % total (Relevant only)"]
        diff_100 = summary["Difference from 100%"]

        if isinstance(recalc_total, float) and not np.isnan(recalc_total):
            badge = "✅ OK" if abs(diff_100) < 1e-6 or abs(diff_100) < 0.01 else "⚠️ Check rounding/data"
            m6.metric("Recalc % total", f"{recalc_total:.6f}%")
            m7.metric("Diff from 100%", f"{diff_100:.6f} ({badge})")
        else:
            st.warning("recalc sum이 0 이하이거나 계산 불가해서 Recalc %를 계산하지 못했어요. (Air/Si/No data 비율이 너무 크거나 Area가 비어있을 수 있어요.)")

        st.divider()

        st.subheader("Output table")

        show_excluded = st.toggle("Show excluded rows (Air / Si peak / No data)", value=False)

        out_cols = ["Peak", "RT", "Area", "Height", "Area %", "Recalc %", "Name", "Formula", "Species", "Score", "Category"]
        present_cols = [c for c in out_cols if c in df_calc.columns]
        out = df_calc[present_cols].copy()

        # filter
        if not show_excluded:
            out = out[out["Category"] == "Relevant"].copy()

        # default sort
        if "Recalc %" in out.columns:
            out = out.sort_values(by=["Recalc %"], ascending=False, na_position="last")

        # Display formatting (don’t mutate numeric types for download)
        display_df = out.copy()
        for c in ["RT", "Area", "Height", "Score"]:
            if c in display_df.columns:
                display_df[c] = display_df[c].apply(lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}")
        for c in ["Area %", "Recalc %"]:
            if c in display_df.columns:
                display_df[c] = display_df[c].apply(lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}")

        # keep requested columns only in display
        requested_display_cols = ["Peak", "RT", "Area", "Height", "Area %", "Recalc %", "Name", "Formula", "Species", "Score"]
        display_cols = [c for c in requested_display_cols if c in display_df.columns]
        st.dataframe(display_df[display_cols], use_container_width=True, hide_index=True)

        # Downloads
        st.subheader("Download / Copy")

        csv_bytes = out[requested_display_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name="recalc_output.csv",
            mime="text/csv",
        )

        # TSV copy block
        tsv_text = out[requested_display_cols].to_csv(index=False, sep="\t")
        st.text_area("Copy as TSV", value=tsv_text, height=160)

    except Exception as e:
        st.error(str(e))
        st.stop()

else:
    st.caption("위에 데이터를 붙여넣고 **Calculate**를 누르면 계산 결과가 나와요.")
