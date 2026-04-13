import io
import re
import pandas as pd
import numpy as np
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="GC-MS Data Cleaning", layout="wide")

REQUIRED_COLS = ["Peak", "RT", "Area", "Height", "Name", "Formula", "Species", "Score"]
EMPTY_TOKENS = {"nan": "", "None": "", "none": "", "—": "", "-": ""}

st.title("GC-MS Data Cleaning 🫧")

ANALYSIS_APP_URL = "https://gcms-analyze-gm8cqhckpwmym6caacqkqn.streamlit.app/"
with st.sidebar:
    st.markdown("### Navigation")
    st.link_button("🧪 Go to Analysis Web", ANALYSIS_APP_URL)

st.caption(
    "Paste an Excel table (tab-separated) below. "
    "The app calculates Area sums, excludes Air/Si/No-data peaks, "
    "can optionally exclude suspicious contamination peaks, "
    "and helps resolve duplicate compound names."
)

# ---------- UI ----------
exclude_suspicious = st.checkbox(
    "Exclude obvious suspicious contamination / misidentification peaks",
    value=True,
    help="Examples: brominated compounds, nitro-containing compounds, anilino compounds, clear plasticizer-like compounds, and unstable library matches."
)

duplicate_rt_threshold = st.number_input(
    "RT threshold for duplicate-name flagging",
    min_value=0.05,
    max_value=5.0,
    value=0.30,
    step=0.05,
    help="This only affects warning flags, not which duplicate groups appear."
)

duplicate_mode = st.radio(
    "Duplicate handling mode",
    ["Recommended only", "Keep all duplicates", "Manual selection"],
    index=0,
    help=(
        "Recommended only: keep the best peak in each duplicate-name group "
        "(highest Score, then highest Area). "
        "Keep all duplicates: do not remove duplicate-name peaks. "
        "Manual selection: choose peaks yourself."
    )
)

st.caption(
    "RT threshold only affects warning flags. Duplicate handling mode controls what is kept in the final cleaned table."
)

calc = st.button("Calculate", type="primary")

if "df_calc" not in st.session_state:
    st.session_state.df_calc = None

if "summary" not in st.session_state:
    st.session_state.summary = None

if "last_raw" not in st.session_state:
    st.session_state.last_raw = ""

raw = st.text_area(
    "Paste your Excel table here (including header row):",
    height=260,
    placeholder="Paste tab-separated data copied directly from Excel…",
)

# ---------- Clipboard copy button ----------
def copy_to_clipboard_button(text: str, label: str = "🗒️ Copy"):
    safe_text = (
        text.replace("\\", "\\\\")
            .replace("`", "\\`")
            .replace("${", "\\${")
    )
    html = f"""
    <button style="
        width:100%;
        padding:0.6rem 1rem;
        border-radius:0.75rem;
        border:1px solid rgba(49, 51, 63, 0.25);
        background:white;
        cursor:pointer;
        font-size:0.95rem;
        font-weight:600;
    " onclick="navigator.clipboard.writeText(`{safe_text}`).then(() => {{
        const el = document.getElementById('copy-status');
        if (el) {{
            el.innerText = 'Copied!';
            setTimeout(() => el.innerText = '', 1200);
        }}
    }});">
        {label}
    </button>
    <div id="copy-status" style="margin-top:0.4rem;font-size:0.85rem;opacity:0.7;"></div>
    """
    components.html(html, height=90)

# ---------- Helpers ----------
def _coerce_number(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.replace(",", "", regex=False).str.strip()
    s = s.replace(EMPTY_TOKENS)
    s = s.replace({"": np.nan})
    return pd.to_numeric(s, errors="coerce")

def parse_tsv(text: str) -> pd.DataFrame:
    if not text or not text.strip():
        raise ValueError("Input is empty. Please paste a table copied from Excel.")

    df = pd.read_csv(io.StringIO(text.strip()), sep="\t", dtype=str, engine="python")
    df.columns = [c.strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Missing required columns: {missing}\n"
            f"Detected columns: {list(df.columns)}"
        )

    for c in df.columns:
        df[c] = df[c].astype(str).str.strip().replace(EMPTY_TOKENS)

    df["Peak"] = _coerce_number(df["Peak"]).astype("Int64")
    df["RT"] = _coerce_number(df["RT"])
    df["Area"] = _coerce_number(df["Area"])
    df["Height"] = _coerce_number(df["Height"])
    df["Score"] = _coerce_number(df["Score"])

    return df

def choose_best_duplicate_peak(group: pd.DataFrame):
    """
    Choose the best representative peak within a duplicate-name group.
    Priority:
    1) higher Score
    2) higher Area
    3) lower RT
    """
    g = group.copy()

    g["Score_sort"] = pd.to_numeric(g["Score"], errors="coerce").fillna(-1)
    g["Area_sort"] = pd.to_numeric(g["Area"], errors="coerce").fillna(-1)
    g["RT_sort"] = pd.to_numeric(g["RT"], errors="coerce").fillna(np.inf)

    g = g.sort_values(
        by=["Score_sort", "Area_sort", "RT_sort"],
        ascending=[False, False, True]
    )

    return g.iloc[0]["Peak"]

def flag_name_rt_duplicates(df: pd.DataFrame, rt_threshold: float = 0.3) -> pd.DataFrame:
    out = df.copy()

    if "Name" not in out.columns or "RT" not in out.columns:
        out["Duplicate Name Flag"] = ""
        out["Duplicate Group RT Range"] = ""
        out["Same Name Count"] = 1
        return out

    out["Duplicate Name Flag"] = ""
    out["Duplicate Group RT Range"] = ""

    norm_name = (
        out["Name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    out["_norm_name_tmp"] = norm_name

    name_counts = out["_norm_name_tmp"].value_counts()
    out["Same Name Count"] = out["_norm_name_tmp"].map(name_counts).fillna(0).astype(int)

    valid = out[out["_norm_name_tmp"] != ""].copy()

    for _, group in valid.groupby("_norm_name_tmp"):
        if len(group) < 2:
            continue

        rts = group["RT"].dropna().sort_values()
        if len(rts) < 2:
            continue

        rt_min = rts.min()
        rt_max = rts.max()
        rt_range = rt_max - rt_min

        if rt_range > rt_threshold:
            idx = group.index
            out.loc[idx, "Duplicate Name Flag"] = "Possible duplicate / RT mismatch"
            out.loc[idx, "Duplicate Group RT Range"] = f"{rt_min:.3f}–{rt_max:.3f}"

    out = out.drop(columns=["_norm_name_tmp"], errors="ignore")
    return out

def get_duplicate_name_groups(df: pd.DataFrame) -> dict:
    temp = df.copy()
    temp["_norm_name"] = (
        temp["Name"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    temp = temp[temp["_norm_name"] != ""]
    counts = temp["_norm_name"].value_counts()
    dup_names = counts[counts > 1].index.tolist()

    groups = {}
    for nm in dup_names:
        grp = temp[temp["_norm_name"] == nm].copy().sort_values("RT", ascending=True)
        groups[nm] = grp

    return groups

def render_duplicate_selector(df: pd.DataFrame, mode: str) -> set:
    selected_duplicate_peaks = set()
    dup_groups = get_duplicate_name_groups(df)

    if not dup_groups:
        return selected_duplicate_peaks

    st.subheader("Resolve duplicate compound names")

    if mode == "Manual selection":
        st.caption(
            "The same compound name appears more than once. "
            "All peaks are pre-selected so you can manually remove the ones you do not want."
        )
    else:
        st.caption(
            "The same compound name appears more than once. "
            "A recommended peak is pre-selected based on highest Score, then highest Area."
        )

    for norm_name, grp in dup_groups.items():
        display_name = grp["Name"].iloc[0]
        best_peak = choose_best_duplicate_peak(grp)

        with st.expander(f"{display_name} ({len(grp)} peaks)"):
            options = []
            default_options = []

            for _, row in grp.iterrows():
                peak_val = row["Peak"]
                rt_val = row["RT"]
                area_val = row["Area"]
                score_val = row["Score"]
                formula_val = row["Formula"]
                species_val = row["Species"]

                peak_text = "—" if pd.isna(peak_val) else str(int(peak_val))
                rt_text = "—" if pd.isna(rt_val) else f"{float(rt_val):.3f}"
                area_text = "—" if pd.isna(area_val) else f"{float(area_val):,.0f}"
                score_text = "—" if pd.isna(score_val) else f"{float(score_val):.2f}"

                recommended_tag = " ⭐ Recommended" if peak_val == best_peak else ""

                label = (
                    f"Peak {peak_text} | RT {rt_text} | "
                    f"Area {area_text} | Score {score_text} | "
                    f"Formula {formula_val} | Species {species_val}{recommended_tag}"
                )

                options.append((label, peak_val))

                if mode == "Manual selection":
                    default_options.append(label)   # manual = all selected
                else:
                    if peak_val == best_peak:
                        default_options.append(label)  # recommended only

            selected_labels = st.multiselect(
                f"Choose peaks to keep for {display_name}",
                options=[x[0] for x in options],
                default=default_options,
                key=f"dup_select_{mode}_{norm_name}"   # mode 포함해서 상태 분리
            )

            label_to_peak = {label: peak for label, peak in options}
            selected_peaks_here = {
                label_to_peak[label]
                for label in selected_labels
                if pd.notna(label_to_peak[label])
            }
            selected_duplicate_peaks.update(selected_peaks_here)

    return selected_duplicate_peaks
def apply_duplicate_selection(df: pd.DataFrame, mode: str, selected_peaks: set = None) -> pd.DataFrame:
    out = df.copy()
    dup_groups = get_duplicate_name_groups(out)

    if not dup_groups:
        return out

    keep_peaks = set()

    for _, grp in dup_groups.items():
        if mode == "Keep all duplicates":
            keep_peaks.update(grp["Peak"].dropna().tolist())

        elif mode == "Recommended only":
            best_peak = choose_best_duplicate_peak(grp)
            keep_peaks.add(best_peak)

        elif mode == "Manual selection":
            if selected_peaks:
                keep_peaks.update(selected_peaks)

    duplicate_peaks_all = set()
    for grp in dup_groups.values():
        duplicate_peaks_all.update(grp["Peak"].dropna().tolist())

    non_duplicate_mask = ~out["Peak"].isin(duplicate_peaks_all)

    final = pd.concat([
        out[non_duplicate_mask],
        out[out["Peak"].isin(keep_peaks)]
    ])

    return final

def is_suspicious_contamination_row(name: str, formula: str, species: str) -> bool:
    name = "" if pd.isna(name) else str(name).strip().lower()
    formula = "" if pd.isna(formula) else str(formula).strip().lower()
    species = "" if pd.isna(species) else str(species).strip().lower()

    combined = f"{name} {species} {formula}"

    exact_suspicious_names = [
        "4-anilino-2-methyl-2-pentanol",
        "2-adamantanol, 2-(bromomethyl)-",
        "ethylene glycol di-n-butyrate",
        "acetic acid, 3-acetoxy-1-ethyl-2-nitrobutyl ester",
        "4-ethylbenzoic acid, 2-ethylcyclohexyl ester",
        "2,2,3,4-tetramethyl-5-phenyloxazolidine",
        "benzene, hexamethyl-",
        "3-nonen-5-yne, 4-ethyl-",
        "1,3-cyclopentadiene, 1,2,3,4,5-pentamethyl-",
        "1h-3a,7-methanoazulene",
        "14-hydroxycaryophyllene",
    ]
    if any(x in name for x in exact_suspicious_names):
        return True

    suspicious_keywords = [
        "ageratriol",
        "cyclooctatin",
        "parthenolide",
        "methanoazulene",
        "neointermedeol",
        "hydroxycaryophyllene",
        "oxazolidine",
    ]
    if any(x in combined for x in suspicious_keywords):
        return True

    halogen_words = ["bromo", "chloro", "fluoro", "iodo"]
    if any(x in combined for x in halogen_words):
        return True

    formula_upper = formula.upper()
    if ("BR" in formula_upper) or ("CL" in formula_upper):
        return True

    if "nitro" in combined or "anilino" in combined or "oxazolidine" in combined:
        return True

    if re.search(r"\dD\d|\dD$|[A-Z]D\d", formula.upper()):
        return True

    return False

def suspicious_reason(name: str, formula: str, species: str) -> str:
    name_l = "" if pd.isna(name) else str(name).strip().lower()
    formula_l = "" if pd.isna(formula) else str(formula).strip().lower()
    species_l = "" if pd.isna(species) else str(species).strip().lower()
    combined = f"{name_l} {species_l} {formula_l}"

    if "4-anilino-2-methyl-2-pentanol" in name_l:
        return "Implausible amino alcohol for hydrolat"
    if "2-adamantanol, 2-(bromomethyl)-" in name_l:
        return "Halogenated compound; likely false match"
    if "ethylene glycol di-n-butyrate" in name_l:
        return "Likely plasticizer / material contamination"
    if "acetic acid, 3-acetoxy-1-ethyl-2-nitrobutyl ester" in name_l:
        return "Nitro-containing match; implausible for hydrolat"
    if "4-ethylbenzoic acid, 2-ethylcyclohexyl ester" in name_l:
        return "Likely plastic/material contamination"
    if "2,2,3,4-tetramethyl-5-phenyloxazolidine" in name_l:
        return "Implausible N-containing cyclic compound for hydrolat"
    if "benzene, hexamethyl-" in name_l:
        return "Unlikely aromatic hydrocarbon; probable artifact/mis-ID"
    if "3-nonen-5-yne, 4-ethyl-" in name_l:
        return "Implausible hydrocarbon match for hydrolat"
    if "1,3-cyclopentadiene, 1,2,3,4,5-pentamethyl-" in name_l:
        return "Likely artifact / implausible fully methylated hydrocarbon"
    if "1h-3a,7-methanoazulene" in name_l or "methanoazulene" in combined:
        return "Unstable sesquiterpene-type library match"
    if "14-hydroxycaryophyllene" in combined or "hydroxycaryophyllene" in combined:
        return "Late RT oxygenated sesquiterpene; likely misidentification"
    if "neointermedeol" in combined:
        return "Unstable sesquiterpene-type library match"
    if "oxazolidine" in combined:
        return "Implausible N-containing cyclic compound for hydrolat"
    if "ageratriol" in combined or "cyclooctatin" in combined or "parthenolide" in combined:
        return "Unstable / implausible library match"
    if "bromo" in combined or "chloro" in combined or "fluoro" in combined or "iodo" in combined:
        return "Halogenated compound; implausible in hydrolat"
    if ("BR" in formula_l.upper()) or ("CL" in formula_l.upper()):
        return "Halogenated formula; implausible in hydrolat"
    if "nitro" in combined:
        return "Nitro-containing match; suspicious"
    if "anilino" in combined:
        return "Aniline-like match; suspicious"
    if re.search(r"\dD\d|\dD$|[A-Z]D\d", formula_l.upper()):
        return "Deuterium-containing formula; likely library confusion"
    return ""

def classify_rows(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    peak = out["Peak"]
    formula = out["Formula"].fillna("").astype(str).str.strip().replace(EMPTY_TOKENS)

    category = pd.Series(["Relevant"] * len(out), index=out.index)
    reason = pd.Series([""] * len(out), index=out.index)

    air_mask = peak == 1
    si_mask = (~air_mask) & formula.str.contains("si", case=False, na=False)
    nodata_mask = (
        (~air_mask)
        & (~si_mask)
        & (
            (formula == "")
            | (formula.str.lower() == "formula")
        )
    )

    suspicious_mask = (
        (~air_mask)
        & (~si_mask)
        & (~nodata_mask)
        & out.apply(
            lambda row: is_suspicious_contamination_row(
                row.get("Name", ""),
                row.get("Formula", ""),
                row.get("Species", "")
            ),
            axis=1
        )
    )

    category.loc[air_mask] = "Air peak"
    category.loc[si_mask] = "Si peak"
    category.loc[nodata_mask] = "No data"
    category.loc[suspicious_mask] = "Suspicious contamination"

    reason.loc[air_mask] = "Peak 1 treated as air peak"
    reason.loc[si_mask] = "Formula contains Si"
    reason.loc[nodata_mask] = "Missing formula / no identification"
    reason.loc[suspicious_mask] = out.loc[suspicious_mask].apply(
        lambda row: suspicious_reason(row.get("Name", ""), row.get("Formula", ""), row.get("Species", "")),
        axis=1
    )

    out["Category"] = category
    out["Reason"] = reason
    return out

def compute(df: pd.DataFrame, exclude_suspicious_flag: bool, duplicate_rt_threshold: float):
    df = classify_rows(df)
    df = flag_name_rt_duplicates(df, rt_threshold=duplicate_rt_threshold)

    always_excluded = ["Air peak", "Si peak", "No data"]
    excluded_categories = always_excluded.copy()
    if exclude_suspicious_flag:
        excluded_categories.append("Suspicious contamination")

    area_sum = df["Area"].sum(skipna=True)
    air_sum = df.loc[df["Category"] == "Air peak", "Area"].sum(skipna=True)
    si_sum = df.loc[df["Category"] == "Si peak", "Area"].sum(skipna=True)
    nodata_sum = df.loc[df["Category"] == "No data", "Area"].sum(skipna=True)
    suspicious_sum = df.loc[df["Category"] == "Suspicious contamination", "Area"].sum(skipna=True)

    excluded_sum = df.loc[df["Category"].isin(excluded_categories), "Area"].sum(skipna=True)
    recalc_sum = area_sum - excluded_sum

    df["Area %"] = np.nan
    if area_sum > 0:
        df["Area %"] = (df["Area"] / area_sum) * 100

    df["Recalc %"] = np.nan
    relevant_mask = ~df["Category"].isin(excluded_categories)

    if recalc_sum > 0:
        df.loc[relevant_mask, "Recalc %"] = (df.loc[relevant_mask, "Area"] / recalc_sum) * 100
        recalc_total = df.loc[relevant_mask, "Recalc %"].sum(skipna=True)
        diff_100 = recalc_total - 100
    else:
        recalc_total = np.nan
        diff_100 = np.nan

    summary = {
        "Area sum": area_sum,
        "Air peak sum": air_sum,
        "Si peak sum": si_sum,
        "No data sum": nodata_sum,
        "Suspicious contamination sum": suspicious_sum,
        "Excluded sum": excluded_sum,
        "Recalc sum": recalc_sum,
        "Recalc % total": recalc_total,
        "Difference from 100%": diff_100,
        "Excluded categories": excluded_categories,
    }

    return df, summary

# ---------- Main ----------
if calc:
    try:
        df = parse_tsv(raw)
        df_calc, summary = compute(df, exclude_suspicious, duplicate_rt_threshold)

        st.session_state.df_calc = df_calc
        st.session_state.summary = summary
        st.session_state.last_raw = raw

    except Exception as e:
        st.error(str(e))

if st.session_state.df_calc is not None and st.session_state.summary is not None:
    df_calc = st.session_state.df_calc
    summary = st.session_state.summary

    st.subheader("Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Area sum", f"{summary['Area sum']:,.2f}")
    c2.metric("Air peak sum", f"{summary['Air peak sum']:,.2f}")
    c3.metric("Si peak sum", f"{summary['Si peak sum']:,.2f}")

    c4, c5, c6 = st.columns(3)
    c4.metric("No data sum", f"{summary['No data sum']:,.2f}")
    c5.metric("Suspicious sum", f"{summary['Suspicious contamination sum']:,.2f}")
    c6.metric("Recalc sum", f"{summary['Recalc sum']:,.2f}")

    excluded_text = ", ".join(summary["Excluded categories"])
    st.caption(f"Currently excluded from Recalc %: {excluded_text}")

    if not np.isnan(summary["Recalc % total"]):
        status = "✅ OK" if abs(summary["Difference from 100%"]) < 0.01 else "⚠️ Check"
        st.info(
            f"Recalc % total: {summary['Recalc % total']:.6f}%  \n"
            f"Difference from 100%: {summary['Difference from 100%']:.6f} ({status})"
        )
    else:
        st.warning(
            "Recalc % could not be computed because recalc sum is ≤ 0. "
            "This usually means excluded peaks dominate the Area."
        )

    st.divider()
    st.subheader("Cleaned Output Table")

    show_excluded = st.toggle("Show excluded peaks", value=False)

    out_cols = [
        "Peak", "RT", "Area", "Height",
        "Area %", "Recalc %",
        "Name", "Formula", "Species", "Score",
        "Category", "Reason",
        "Duplicate Name Flag", "Duplicate Group RT Range", "Same Name Count"
    ]
    out = df_calc[out_cols].copy()

    if not show_excluded:
        out = out[~out["Category"].isin(summary["Excluded categories"])]

    duplicate_groups = get_duplicate_name_groups(out)

    selected_duplicate_peaks = None
    if duplicate_groups and duplicate_mode == "Manual selection":
        selected_duplicate_peaks = render_duplicate_selector(out, duplicate_mode)

    out = apply_duplicate_selection(
        out,
        mode=duplicate_mode,
        selected_peaks=selected_duplicate_peaks
    )

    out = out.sort_values(by="Recalc %", ascending=False, na_position="last")

    display_cols = [
        "Peak", "RT", "Area", "Height",
        "Area %", "Recalc %",
        "Name", "Formula", "Species", "Score",
        "Category", "Reason",
        "Duplicate Name Flag", "Duplicate Group RT Range", "Same Name Count"
    ]

    display_df = out[display_cols].copy()
    for c in ["RT", "Area", "Height", "Score"]:
        display_df[c] = display_df[c].apply(lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}")
    for c in ["Area %", "Recalc %"]:
        display_df[c] = display_df[c].apply(lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}")

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    suspicious_only = df_calc[df_calc["Category"] == "Suspicious contamination"].copy()
    if not suspicious_only.empty:
        with st.expander("See suspicious contamination peaks"):
            suspicious_view = suspicious_only[
                ["Peak", "RT", "Name", "Formula", "Species", "Score", "Reason"]
            ].copy()
            for c in ["RT", "Score"]:
                suspicious_view[c] = suspicious_view[c].apply(
                    lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}"
                )
            st.dataframe(suspicious_view, use_container_width=True, hide_index=True)

    duplicate_only = df_calc[df_calc["Duplicate Name Flag"] != ""].copy()
    if not duplicate_only.empty:
        with st.expander("See possible duplicate-name RT mismatches"):
            dup_view = duplicate_only[
                [
                    "Peak", "RT", "Name", "Formula", "Species", "Score",
                    "Duplicate Name Flag", "Duplicate Group RT Range", "Same Name Count"
                ]
            ].copy()
            for c in ["RT", "Score"]:
                dup_view[c] = dup_view[c].apply(
                    lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}"
                )
            st.dataframe(dup_view, use_container_width=True, hide_index=True)

    st.subheader("Copy / Download")

    export_cols = [
        "Peak", "RT", "Area", "Height",
        "Area %", "Recalc %",
        "Name", "Formula", "Species", "Score"
    ]
    export_df = out[export_cols].copy()

    tsv_text = export_df.to_csv(index=False, sep="\t")

    b1, b2 = st.columns(2)
    with b1:
        copy_to_clipboard_button(tsv_text, label="🗒️ Copy")
    with b2:
        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⤵ Download",
            csv_bytes,
            file_name="gcms_recalc_cleaned.csv",
            mime="text/csv",
            use_container_width=True,
        )
