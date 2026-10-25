from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import dash
from dash import Dash, Input, Output, State, dcc, html
import flask
import pandas as pd
import plotly.graph_objects as go

# Base directories
APP_DIR = Path(__file__).resolve().parent
PROFILES_FILE = APP_DIR / "trend_profiles.json"
REPORTS_DIR = APP_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def resolve_logs_base_dir() -> Path:
    """Deteta automaticamente a pasta 'SCIA logs' em qualquer sistema operativo (Windows, macOS, Linux ou WSL)."""
    candidates: list[Path] = []

    local_dir = APP_DIR / "SCIA logs"
    if local_dir.exists():
        candidates.append(local_dir)

    user_dirs: list[Path] = []
    try:
        user_dirs.append(Path.home())
    except Exception:
        pass

    wsl_users = Path("/mnt/c/Users")
    if wsl_users.exists():
        try:
            for u in wsl_users.iterdir():
                if u.is_dir() and u.name not in {
                    "Public",
                    "Default",
                    "Default User",
                    "All Users",
                }:
                    user_dirs.append(u)
        except Exception:
            pass

    for u_dir in user_dirs:
        try:
            roots = [u_dir] + [
                d
                for d in u_dir.iterdir()
                if d.is_dir() and "onedrive" in d.name.lower()
            ]
            for r in roots:
                for sub in r.iterdir():
                    if not sub.is_dir():
                        continue
                    s_low = sub.name.lower()
                    if s_low == "scia logs":
                        candidates.append(sub)
                    elif s_low in {
                        "ambiente de trabalho",
                        "desktop",
                        "documents",
                        "documentos",
                    }:
                        for item in sub.iterdir():
                            if (
                                item.is_dir()
                                and item.name.lower() == "scia logs"
                            ):
                                candidates.append(item)
        except Exception:
            continue

    if not candidates:
        local_dir.mkdir(exist_ok=True)
        return local_dir

    def count_runs(p: Path) -> int:
        try:
            return sum(
                1
                for d in p.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            )
        except Exception:
            return 0

    return max(candidates, key=count_runs)


LOGS_BASE_DIR = resolve_logs_base_dir()

OLD_ASSETS_DIR = APP_DIR / "assets"
if OLD_ASSETS_DIR.exists():
    shutil.rmtree(OLD_ASSETS_DIR, ignore_errors=True)

PARAMETER_COLORS = [
    "#1F77B4",  # Technical Blue
    "#D62728",  # Crimson Red
    "#2CA02C",  # Forest Green
    "#9467BD",  # Amethyst Purple
    "#FF7F0E",  # Amber Orange
    "#17BECF",  # Teal Cyan
    "#E377C2",  # Magenta
    "#7F7F7F",  # Slate Gray
]

DEFAULT_PROFILES = {
    "Overview": [
        "PM_Chamber_Pressure_[mbar]",
        "PM_MFC2_Flow_[sccm]",
        "PM_Mag1_DC_Power[W]",
    ],
    "Vacuum & Pumping": [
        "PM_Chamber_Pressure_[mbar]",
        "PM_Foreline_Pressure_[mbar]",
        "TM_Chamber_Pressure_[mbar]",
        "LL_Chamber_Pressure_[mbar]",
    ],
    "Gas System (MFCs)": [
        "PM_MFC1_Flow_[sccm]",
        "PM_MFC2_Flow_[sccm]",
        "PM_MFC3_Flow_[sccm]",
        "PM_MFC4_Flow_[sccm]",
    ],
    "DC Sputtering (Mag1)": [
        "PM_Mag1_DC_Power[W]",
        "PM_Mag1_DC_Voltage_[V]",
        "PM_Mag1_DC_Current_[A]",
        "PM_Mag1_DC_Impedance_[Ohm]",
    ],
    "Substrate RF Bias": [
        "PM_Bias_Substrate_RF_Voltage_[V]",
        "PM_Bias_Substrate_RF_Forward_Power_[W]",
        "PM_Bias_Substrate_RF_Refl_Power[W]",
    ],
}


def help_badge(help_text: str) -> html.Span:
    """Ícone '?' discreto para ajuda contextual."""
    return html.Span(
        "?",
        className="help-badge",
        **{"data-help": help_text},
    )


def load_trend_profiles() -> dict[str, list[str]]:
    if not PROFILES_FILE.exists():
        save_all_trend_profiles(DEFAULT_PROFILES)
        return DEFAULT_PROFILES.copy()
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            profiles = json.load(f)
            for k, v in DEFAULT_PROFILES.items():
                if k not in profiles:
                    profiles[k] = v
            return profiles
    except Exception as e:
        print(f"Error loading {PROFILES_FILE}: {e}")
        return DEFAULT_PROFILES.copy()


def save_all_trend_profiles(profiles: dict[str, list[str]]) -> None:
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {PROFILES_FILE}: {e}")


def read_trend_sav(filepath: Path) -> pd.DataFrame:
    if not filepath.exists():
        return pd.DataFrame()

    for enc in ["utf-8-sig", "cp1252", "latin1", "utf-16", "utf-16-le"]:
        try:
            df = pd.read_csv(
                filepath,
                sep="\t",
                encoding=enc,
                on_bad_lines="skip",
                low_memory=False,
            )
            df = df.dropna(how="all", axis=1)
            if not df.empty and len(df.columns) > 1:
                df.columns = [
                    str(c).strip().replace("\x00", "") for c in df.columns
                ]
                return df
        except Exception:
            continue
    return pd.DataFrame()


def ole_date_to_datetime(ole_date: float) -> datetime:
    epoch = datetime(1899, 12, 30)
    return epoch + timedelta(days=ole_date)


def extract_run_date_str(run_dir: Path) -> str:
    m = re.search(r"(\d{4})_(\d{2})_(\d{2})", run_dir.name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    for sub in sorted(run_dir.iterdir()):
        if sub.is_dir() and not sub.name.startswith("."):
            for f in sorted(sub.iterdir()):
                if f.is_file() and f.name.lower().endswith(".sav"):
                    m_file = re.search(r"(\d{4})_(\d{2})_(\d{2})", f.name)
                    if m_file:
                        return f"{m_file.group(1)}-{m_file.group(2)}-{m_file.group(3)}"
    return ""


def parse_run_data_sav(run_dir: Path) -> dict:
    info = {
        "Wafer ID": "Unknown",
        "Lot ID": "Unknown",
        "Sequence Name": "Unknown",
        "User": "Unknown",
        "Start Time": "Unknown",
        "End Time": "Unknown",
        "Wafer Size": "Unknown",
        "Wafer State": "Unknown",
        "Source Station": "Unknown",
        "Source Slot": "Unknown",
        "Date": "Unknown",
    }
    if not run_dir.exists():
        return info

    run_date = extract_run_date_str(run_dir)
    if run_date:
        info["Date"] = run_date

    data_files = [
        f
        for f in run_dir.iterdir()
        if f.is_file()
        and "data" in f.name.lower()
        and f.name.lower().endswith(".sav")
        and "trend" not in f.name.lower()
    ]
    if not data_files:
        return info

    target_file = data_files[0]
    raw_bytes = target_file.read_bytes()

    text = ""
    for enc in ["utf-8-sig", "utf-16", "utf-16-le", "cp1252", "latin1"]:
        try:
            candidate = raw_bytes.decode(enc)
            if (
                "Wafer ID" in candidate
                or "Lot ID" in candidate
                or "User" in candidate
            ):
                text = candidate
                break
        except Exception:
            continue

    if not text:
        text = raw_bytes.decode("utf-8", errors="ignore").replace("\x00", "")

    for line in text.splitlines():
        line = line.strip().replace("\x00", "")
        if not line:
            continue
        for field in list(info.keys()):
            if field == "Date":
                continue
            pattern = rf"^{re.escape(field)}\s*[:=\t]\s*(.*)$"
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                val = match.group(1).strip()
                if val:
                    info[field] = val

    if run_date:
        for time_key in ["Start Time", "End Time"]:
            t_val = info.get(time_key, "Unknown")
            if t_val != "Unknown" and not re.search(
                r"\d{4}[-/]\d{2}[-/]\d{2}", t_val
            ):
                info[time_key] = f"{run_date} {t_val}"

    return info


def get_runs_catalog() -> pd.DataFrame:
    global LOGS_BASE_DIR
    LOGS_BASE_DIR = resolve_logs_base_dir()

    if not LOGS_BASE_DIR.exists():
        return pd.DataFrame(
            columns=["Run", "Lot", "Wafer", "Sequence", "User", "Slot"]
        )

    records = []
    for d in sorted(LOGS_BASE_DIR.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            meta = parse_run_data_sav(d)
            lot = meta.get("Lot ID", "Unknown")
            wafer = meta.get("Wafer ID", "Unknown")

            if not lot or lot == "Unknown":
                parts = d.name.split("_202")
                lot = parts[0] if len(parts) > 1 else d.name
            if not wafer or wafer == "Unknown":
                wafer = d.name

            records.append({
                "Run": d.name,
                "Lot": lot,
                "Wafer": wafer,
                "Sequence": meta.get("Sequence Name", "Unknown"),
                "User": meta.get("User", "Unknown"),
                "Slot": meta.get("Source Slot", "Unknown"),
                "StartTime": meta.get("Start Time", "Unknown"),
                "EndTime": meta.get("End Time", "Unknown"),
                "Date": meta.get("Date", "Unknown"),
            })

    return pd.DataFrame(records)


def parse_run_sequence_xml(module_dir: Path) -> dict:
    metadata = {
        "User": "Unknown",
        "RecipeName": "Unknown",
        "steps": {},
    }
    xml_files = sorted([
        f
        for f in module_dir.iterdir()
        if f.is_file() and f.name.lower().endswith(".xml")
    ])
    if not xml_files:
        return metadata

    run_seq_files = [f for f in xml_files if "runsequence" in f.name.lower()]
    target_xml = run_seq_files[0] if run_seq_files else xml_files[0]

    try:
        tree = ET.parse(target_xml)
        root = tree.getroot()
        metadata["User"] = root.attrib.get("User", "Unknown")
        recipe_node = root.find("RecipeName")
        if recipe_node is not None and recipe_node.text:
            metadata["RecipeName"] = recipe_node.text.strip()

        steps_node = root.find("Steps")
        if steps_node is not None:
            for step in steps_node.findall("Step"):
                step_no = int(step.attrib.get("StepNo", 0))
                name_node = step.find("StepName")
                step_name = (
                    name_node.text.strip()
                    if name_node is not None and name_node.text
                    else f"Step {step_no}"
                )
                metadata["steps"][step_no] = {"StepName": step_name}
    except Exception as e:
        print(f"Error parsing XML {target_xml}: {e}")

    if metadata["RecipeName"] == "Unknown":
        fallback_name = re.sub(
            r"_RunSequence\.xml$|\.xml$",
            "",
            target_xml.name,
            flags=re.IGNORECASE,
        )
        metadata["RecipeName"] = fallback_name

    return metadata


def load_recipe_steps_sav(module_dir: Path) -> pd.DataFrame:
    files = sorted([
        f
        for f in module_dir.iterdir()
        if f.is_file()
        and "recipestep" in f.name.lower().replace("_", "").replace(" ", "")
        and f.name.lower().endswith(".sav")
    ])
    if not files:
        return pd.DataFrame()

    dfs = []
    for filepath in files:
        for enc in ["utf-8-sig", "cp1252", "latin1", "utf-16"]:
            try:
                df_s = pd.read_csv(
                    filepath, sep=r"\t+", engine="python", encoding=enc
                )
                df_s.columns = [
                    str(c).strip().replace("\x00", "") for c in df_s.columns
                ]
                if (
                    "StartTime" in df_s.columns
                    and "RecipeStep" in df_s.columns
                ):
                    df_s["StartDateTime"] = pd.to_datetime(
                        df_s["StartTime"], errors="coerce"
                    )
                    if "Sequence" in df_s.columns:
                        df_s["Sequence"] = pd.to_numeric(
                            df_s["Sequence"], errors="coerce"
                        )
                    df_s = df_s.dropna(subset=["StartDateTime"])
                    dfs.append(df_s)
                    break
            except Exception:
                continue

    if not dfs:
        return pd.DataFrame()

    full_steps = pd.concat(dfs, ignore_index=True)
    return full_steps.sort_values("StartDateTime").reset_index(drop=True)


def load_scia_module_data(module_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not module_dir.exists():
        return pd.DataFrame(), pd.DataFrame()

    recipe_info = parse_run_sequence_xml(module_dir)

    trend_files = sorted([
        f
        for f in module_dir.iterdir()
        if f.is_file()
        and "trend" in f.name.lower()
        and f.name.lower().endswith(".sav")
    ])
    all_dfs = []

    for filepath in trend_files:
        match = re.search(r"_Step(\d+)_", filepath.name, re.IGNORECASE)
        step_no = int(match.group(1)) if match else 1

        df_step = read_trend_sav(filepath)
        if df_step.empty:
            continue

        if "Time" in df_step.columns:
            time_num = pd.to_numeric(df_step["Time"], errors="coerce")
            valid_time_num = time_num.dropna()
            if not valid_time_num.empty and valid_time_num.iloc[0] > 30000:
                df_step["DateTime"] = time_num.dropna().apply(
                    ole_date_to_datetime
                )
            else:
                df_step["DateTime"] = pd.to_datetime(
                    df_step["Time"], errors="coerce"
                )

        df_step["StepNo"] = step_no
        df_step["RecipeName"] = recipe_info["RecipeName"]
        df_step["User"] = recipe_info["User"]

        if all_dfs and "DateTime" in all_dfs[-1].columns:
            prev_dates = all_dfs[-1]["DateTime"].dropna()
            if not prev_dates.empty:
                last_dt = prev_dates.iloc[-1]
                gap_row = pd.DataFrame(
                    [{c: float("nan") for c in df_step.columns}]
                )
                gap_row["DateTime"] = last_dt + timedelta(milliseconds=10)
                gap_row["RecipeName"] = recipe_info["RecipeName"]
                gap_row["User"] = recipe_info["User"]
                all_dfs.append(gap_row)

        all_dfs.append(df_step)

    if not all_dfs:
        return pd.DataFrame(), pd.DataFrame()

    full_df = pd.concat(all_dfs, ignore_index=True)

    meta_cols = {
        "Time",
        "DateTime",
        "StepNo",
        "RecipeName",
        "User",
        "Total_ElapsedTime_s",
    }
    for c in full_df.columns:
        if c not in meta_cols:
            if not pd.api.types.is_numeric_dtype(full_df[c]):
                full_df[c] = pd.to_numeric(
                    full_df[c].astype(str).str.replace(",", "."),
                    errors="coerce",
                )

    if "DateTime" in full_df.columns:
        valid_dates = full_df["DateTime"].dropna()
        if not valid_dates.empty:
            t0 = valid_dates.iloc[0]
            full_df["Total_ElapsedTime_s"] = (
                full_df["DateTime"] - t0
            ).dt.total_seconds()
        else:
            full_df["Total_ElapsedTime_s"] = range(len(full_df))
    else:
        full_df["Total_ElapsedTime_s"] = range(len(full_df))

    df_recipe_steps = load_recipe_steps_sav(module_dir)
    return full_df, df_recipe_steps


def module_has_trend_data(module_dir: Path) -> bool:
    if not module_dir.exists() or not module_dir.is_dir():
        return False
    return any(
        f.is_file()
        and "trend" in f.name.lower()
        and f.name.lower().endswith(".sav")
        for f in module_dir.iterdir()
    )


def get_active_modules_for_run(run_path: Path) -> list[str]:
    if not run_path.exists():
        return []
    active_subfolders = [
        d.name
        for d in sorted(run_path.iterdir())
        if d.is_dir() and not d.name.startswith(".") and module_has_trend_data(d)
    ]
    if active_subfolders:
        return active_subfolders
    if module_has_trend_data(run_path):
        return ["."]
    return []


def extract_unit(column_name: str) -> str:
    match = re.search(r"_\[(.*?)\]", column_name)
    if match:
        return match.group(1)
    if column_name.endswith("[W]"):
        return "W"
    if column_name.endswith("_s"):
        return "s"
    return ""


def clean_column_label(col: str) -> str:
    cleaned = col.replace("PM_", "").replace("TM_", "TM ").replace("LL_", "LL ")
    return cleaned


def short_module_name(mod_name: str) -> str:
    if mod_name == ".":
        return "Main"
    m = re.search(r"Process\s*Module\s*(\d+)", mod_name, re.IGNORECASE)
    if m:
        return f"PM{m.group(1)}"
    return mod_name


def build_multi_axis_layout(
    selected_columns: list[str],
    x_axis: str,
    pressure_mode: str,
) -> tuple[dict, dict[str, str], dict[str, str]]:
    unit_groups: dict[str, list[str]] = {}
    for col in selected_columns:
        unit = extract_unit(col) or "Other"
        unit_groups.setdefault(unit, []).append(col)

    groups = list(unit_groups.keys())
    axis_count = len(groups)
    extra_right_axes = max(0, axis_count - 1)
    right_space = min(0.28, 0.08 * extra_right_axes)
    domain_end = 1 - right_space

    x_title = (
        "Total Elapsed Time (s)"
        if x_axis == "Total_ElapsedTime_s"
        else "Date / Time"
    )
    layout = {
        "xaxis": {
            "domain": [0, domain_end],
            "title": {"text": x_title},
        }
    }

    colors = {
        group: PARAMETER_COLORS[i % len(PARAMETER_COLORS)]
        for i, group in enumerate(groups)
    }
    axis_map = {}

    for index, group in enumerate(groups):
        color = colors[group]
        axis_key = "yaxis" if index == 0 else f"yaxis{index + 1}"
        is_pressure = any("Pressure" in col for col in unit_groups[group])

        if is_pressure and pressure_mode == "log":
            axis_title_text = f"Scale [{group}] (Log)"
            axis_type = "log"
        else:
            axis_title_text = f"Scale [{group}]"
            axis_type = "linear"

        axis_config = {
            "title": {"text": axis_title_text, "font": {"color": color}},
            "tickfont": {"color": color},
            "linecolor": color,
            "linewidth": 2,
            "showline": True,
            "zeroline": False,
            "type": axis_type,
        }

        if index == 0:
            axis_config["side"] = "left"
        else:
            pos = (
                1
                if extra_right_axes <= 1
                else domain_end
                + ((index - 1) * right_space / (extra_right_axes - 1))
            )
            axis_config.update(
                {
                    "anchor": "free",
                    "overlaying": "y",
                    "side": "right",
                    "position": pos,
                }
            )

        layout[axis_key] = axis_config
        for col in unit_groups[group]:
            axis_map[col] = "y" if index == 0 else f"y{index + 1}"

    return layout, colors, axis_map


def get_step_boundaries(
    df: pd.DataFrame, df_steps: pd.DataFrame, x_col: str
) -> list[dict]:
    boundaries = []

    if not df_steps.empty and "Sequence" in df_steps.columns:
        t_col = (
            "ElapsedTime_s" if x_col == "Total_ElapsedTime_s" else "StartDateTime"
        )
        if t_col in df_steps.columns:
            for seq_no, group in df_steps.groupby("Sequence", sort=True):
                if pd.isna(seq_no):
                    continue
                t_min = group[t_col].min()
                t_max = group[t_col].max()
                if pd.notna(t_min) and pd.notna(t_max) and t_min < t_max:
                    boundaries.append(
                        {
                            "StepNo": int(seq_no),
                            "min": t_min,
                            "max": t_max,
                        }
                    )
            if boundaries:
                return boundaries

    valid_df = df.dropna(subset=["StepNo", x_col])
    if not valid_df.empty:
        raw_steps = (
            valid_df.groupby(["StepNo"], sort=False)[x_col]
            .agg(["min", "max"])
            .reset_index()
        )
        step_records = raw_steps.to_dict("records")
        for i, s in enumerate(step_records):
            t0 = s["min"]
            t1 = s["max"]
            if i + 1 < len(step_records):
                next_t0 = step_records[i + 1]["min"]
                if t1 > next_t0:
                    t1 = next_t0
            boundaries.append(
                {
                    "StepNo": int(s["StepNo"]),
                    "min": t0,
                    "max": t1,
                }
            )

    return boundaries


def add_steps_to_figure(
    fig: go.Figure,
    df: pd.DataFrame,
    df_steps: pd.DataFrame,
    x_col: str,
    toggle_steps: list[str],
    expanded_steps: list[str],
    color_offset: int = 0,
    mod_tag: str = "",
) -> None:
    if "show" not in (toggle_steps or []):
        return

    palette = [
        "rgba(31, 119, 180, 0.07)",
        "rgba(214, 39, 40, 0.07)",
        "rgba(44, 160, 44, 0.07)",
        "rgba(148, 103, 189, 0.07)",
        "rgba(255, 127, 14, 0.07)",
    ]

    main_steps = get_step_boundaries(df, df_steps, x_col)

    for s_idx, step in enumerate(main_steps):
        t0, t1 = step["min"], step["max"]
        s_no = step["StepNo"]
        if pd.isna(t0) or pd.isna(t1) or t0 >= t1:
            continue

        fig.add_vrect(
            x0=t0,
            x1=t1,
            fillcolor=palette[(s_idx + color_offset) % len(palette)],
            line_width=0,
            layer="below",
        )
        fig.add_vline(
            x=t0,
            line_width=1.4,
            line_dash="dash",
            line_color="rgba(75, 85, 99, 0.6)",
        )
        fig.add_vline(
            x=t1,
            line_width=1.4,
            line_dash="dash",
            line_color="rgba(75, 85, 99, 0.6)",
        )

        label_text = (
            f"<b>Step {s_no} ({mod_tag})</b>"
            if mod_tag
            else f"<b>Step {s_no}</b>"
        )
        fig.add_annotation(
            x=(t0 + t1) / 2 if x_col == "Total_ElapsedTime_s" else t0,
            y=1.02,
            xref="x",
            yref="paper",
            text=label_text,
            showarrow=False,
            font={"size": 11, "color": "#181B1F"},
            textangle=0,
        )

        if str(s_no) in [str(x) for x in (expanded_steps or [])] and not df_steps.empty:
            t_sub_col = (
                "ElapsedTime_s"
                if x_col == "Total_ElapsedTime_s"
                else "StartDateTime"
            )
            if t_sub_col in df_steps.columns and "Sequence" in df_steps.columns:
                matched = (
                    df_steps[df_steps["Sequence"] == s_no]
                    .dropna(subset=[t_sub_col])
                    .to_dict("records")
                )

                for sub_idx, sub in enumerate(matched):
                    t_sub = sub[t_sub_col]
                    fig.add_vline(
                        x=t_sub,
                        line_width=1,
                        line_dash="dot",
                        line_color="rgba(156, 163, 175, 0.8)",
                    )
                    y_sub_pos = 1.08 if sub_idx % 2 == 0 else 1.15
                    fig.add_annotation(
                        x=t_sub,
                        y=y_sub_pos,
                        xref="x",
                        yref="paper",
                        text=f"↳ {sub.get('RecipeStep', '')}",
                        showarrow=False,
                        font={"size": 9, "color": "#4B5563"},
                        textangle=-30,
                        xanchor="left",
                    )


def build_single_plot(
    df: pd.DataFrame,
    df_steps: pd.DataFrame,
    x_col: str,
    y_cols: list[str],
    toggle_steps: list[str],
    expanded_steps: list[str],
    pressure_mode: str,
    title_suffix: str = "",
) -> go.Figure:
    layout, colors, axis_map = build_multi_axis_layout(
        selected_columns=y_cols,
        x_axis=x_col,
        pressure_mode=pressure_mode,
    )
    fig = go.Figure()

    for col in y_cols:
        if col not in df.columns:
            continue
        axis_ref = axis_map[col]

        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[col],
                name=f"{title_suffix} {clean_column_label(col)}".strip(),
                mode="lines",
                line={"width": 1.8},
                yaxis=axis_ref,
                hovertemplate=f"<b>{clean_column_label(col)}</b>: %{{y}}<extra></extra>",
            )
        )

    add_steps_to_figure(
        fig=fig,
        df=df,
        df_steps=df_steps,
        x_col=x_col,
        toggle_steps=toggle_steps,
        expanded_steps=expanded_steps,
        color_offset=0,
        mod_tag="",
    )

    fig.update_layout(
        template="plotly_white",
        font={"family": "'Inter', 'Segoe UI', Arial, sans-serif", "size": 11},
        hovermode="x unified",
        margin={"l": 60, "r": 60, "t": 85, "b": 40},
        legend={"orientation": "h", "y": -0.18},
        **layout,
    )
    return fig


def build_overlaid_plot(
    loaded_data: dict[str, tuple[pd.DataFrame, pd.DataFrame]],
    x_col: str,
    y_cols: list[str],
    toggle_steps: list[str],
    expanded_by_mod: dict[str, list[str]],
    pressure_mode: str,
) -> go.Figure:
    layout, colors, axis_map = build_multi_axis_layout(
        selected_columns=y_cols,
        x_axis=x_col,
        pressure_mode=pressure_mode,
    )
    fig = go.Figure()

    mod_line_styles = ["solid", "3px, 2px", "1px, 2px"]
    for m_idx, (mod, (df, df_steps)) in enumerate(loaded_data.items()):
        dash_style = mod_line_styles[m_idx % len(mod_line_styles)]
        x_use = x_col if x_col in df.columns else "Total_ElapsedTime_s"
        mod_display = "Main Chamber" if mod == "." else mod

        for col in y_cols:
            if col not in df.columns:
                continue
            axis_ref = axis_map[col]

            fig.add_trace(
                go.Scatter(
                    x=df[x_use],
                    y=df[col],
                    name=f"[{mod_display}] {clean_column_label(col)}",
                    mode="lines",
                    line={"width": 1.8, "dash": dash_style},
                    yaxis=axis_ref,
                    hovertemplate=f"<b>[{mod_display}] {clean_column_label(col)}</b>: %{{y}}<extra></extra>",
                )
            )

        add_steps_to_figure(
            fig=fig,
            df=df,
            df_steps=df_steps,
            x_col=x_use,
            toggle_steps=toggle_steps,
            expanded_steps=expanded_by_mod.get(mod, []),
            color_offset=m_idx * 2,
            mod_tag=short_module_name(mod),
        )

    fig.update_layout(
        template="plotly_white",
        font={"family": "'Inter', 'Segoe UI', Arial, sans-serif", "size": 11},
        hovermode="x unified",
        margin={"l": 60, "r": 60, "t": 85, "b": 40},
        legend={"orientation": "h", "y": -0.18},
        **layout,
    )
    return fig


# --- Funções Geradoras de Relatórios (Run Report & Wafer History) ---


def format_stat_val(val: float) -> str:
    if pd.isna(val):
        return "N/A"
    if val == 0:
        return "0.00"
    if abs(val) < 0.01 or abs(val) >= 100000:
        return f"{val:.2e}"
    return f"{val:.2f}"


def build_stats_table_html(df: pd.DataFrame, y_cols: list[str]) -> str:
    rows = []
    for col in y_cols:
        if col not in df.columns:
            continue
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if series.empty:
            continue
        unit = extract_unit(col) or "-"
        rows.append(f"""
            <tr>
                <td><strong>{html_lib.escape(clean_column_label(col))}</strong></td>
                <td>{html_lib.escape(unit)}</td>
                <td class="mono">{format_stat_val(series.min())}</td>
                <td class="mono">{format_stat_val(series.max())}</td>
                <td class="mono">{format_stat_val(series.mean())}</td>
                <td class="mono">{format_stat_val(series.std())}</td>
            </tr>
        """)
    if not rows:
        return "<p>No numeric channel statistics available.</p>"

    return f"""
    <table class="report-table stats-table">
        <thead>
            <tr>
                <th>Parameter (Channel)</th>
                <th>Unit</th>
                <th>Min</th>
                <th>Max</th>
                <th>Mean</th>
                <th>Std Dev</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def build_recipe_steps_table_html(df_steps: pd.DataFrame) -> str:
    if df_steps.empty:
        return "<p style='color:#605E5C; font-size:12px;'>No detailed RecipeSteps.sav file recorded for this module.</p>"

    rows = []
    for _, r in df_steps.iterrows():
        st = str(r.get("StartTime", ""))
        el = (
            f"{float(r['ElapsedTime_s']):.1f} s"
            if "ElapsedTime_s" in r and pd.notna(r["ElapsedTime_s"])
            else "-"
        )
        seq = (
            f"Step {int(r['Sequence'])}"
            if "Sequence" in r and pd.notna(r["Sequence"])
            else "-"
        )
        nr = str(r.get("Nr", "-"))
        action = str(r.get("RecipeStep", ""))
        rows.append(f"""
            <tr>
                <td class="mono">{html_lib.escape(st)}</td>
                <td class="mono">{html_lib.escape(el)}</td>
                <td><strong>{html_lib.escape(seq)}</strong></td>
                <td class="mono">{html_lib.escape(nr)}</td>
                <td class="mono">{html_lib.escape(action)}</td>
            </tr>
        """)

    return f"""
    <table class="report-table steps-table">
        <thead>
            <tr>
                <th>Date / Time</th>
                <th>Elapsed Time</th>
                <th>Main Step</th>
                <th>Substep #</th>
                <th>Recipe Action</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
    """


def wrap_report_document(
    title: str, subtitle: str, body_html: str, filename: str
) -> str:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>{html_lib.escape(title)}</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body {{
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
            color: #201F1E;
            background-color: #EDEBE9;
            margin: 0;
            padding: 20px;
        }}
        .mono {{
            font-family: 'IBM Plex Mono', Consolas, monospace;
            font-size: 11px;
        }}
        .page-container {{
            max-width: 1120px;
            margin: 0 auto;
            background: #FFFFFF;
            padding: 28px;
            border: 1px solid #C8C6C4;
            border-radius: 2px;
        }}
        .top-action-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #181B1F;
            color: #F3F2F1;
            padding: 10px 16px;
            border-radius: 2px;
            margin-bottom: 20px;
            border-bottom: 2px solid #0078D4;
        }}
        .action-btn {{
            background: #0078D4;
            color: #FFFFFF;
            border: 1px solid #005A9E;
            padding: 6px 14px;
            border-radius: 2px;
            font-weight: 600;
            font-size: 12px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-left: 8px;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }}
        .action-btn.secondary {{
            background: #2C3235;
            border-color: #484644;
        }}
        .action-btn:hover {{
            opacity: 0.9;
        }}
        .report-header {{
            border-bottom: 2px solid #323130;
            padding-bottom: 10px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
        }}
        .report-header h1 {{
            margin: 0 0 4px 0;
            font-size: 20px;
            color: #181B1F;
            font-weight: 700;
        }}
        .report-header p {{
            margin: 0;
            color: #605E5C;
            font-size: 12px;
        }}
        .section-card {{
            border: 1px solid #E1DFDD;
            border-radius: 2px;
            padding: 14px;
            margin-bottom: 14px;
            background: #FFFFFF;
        }}
        .section-title {{
            margin: 0 0 10px 0;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.4px;
            color: #181B1F;
            border-left: 3px solid #0078D4;
            padding-left: 8px;
            page-break-after: avoid;
            break-after: avoid;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .meta-box {{
            background: #FAF9F8;
            border: 1px solid #E1DFDD;
            padding: 7px 10px;
            border-radius: 2px;
        }}
        .meta-box .label {{
            font-size: 10px;
            color: #605E5C;
            text-transform: uppercase;
            font-weight: 600;
        }}
        .meta-box .value {{
            font-family: 'IBM Plex Mono', Consolas, monospace;
            font-size: 11.5px;
            color: #201F1E;
            font-weight: 600;
            margin-top: 2px;
            word-break: break-word;
        }}
        .report-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11.5px;
            margin-top: 8px;
        }}
        .stats-table {{
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .report-table tr {{
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        .report-table th, .report-table td {{
            border: 1px solid #E1DFDD;
            padding: 5px 8px;
            text-align: left;
        }}
        .report-table th {{
            background-color: #F3F2F1;
            color: #323130;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .report-table tr:nth-child(even) {{
            background-color: #FAF9F8;
        }}
        .plot-wrapper {{
            width: 100%;
            margin: 8px 0;
            border: 1px solid #E1DFDD;
            border-radius: 2px;
            page-break-inside: avoid;
            break-inside: avoid;
        }}
        @media print {{
            body {{
                background: #FFFFFF !important;
                padding: 0 !important;
                -webkit-print-color-adjust: exact !important;
                print-color-adjust: exact !important;
            }}
            .page-container {{
                border: none !important;
                padding: 0 !important;
                max-width: 100% !important;
            }}
            .no-print {{
                display: none !important;
            }}
            .section-card {{
                margin-bottom: 12px !important;
                padding: 12px !important;
            }}
        }}
    </style>
    <script>
        function downloadStandaloneHTML() {{
            const htmlContent = document.documentElement.outerHTML;
            const blob = new Blob([htmlContent], {{type: 'text/html'}});
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = "{html_lib.escape(filename)}";
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }}
    </script>
</head>
<body>
    <div class="page-container">
        <div class="top-action-bar no-print">
            <div>
                <strong style="font-size: 13px;">SCIA Magna 200  /  Report Viewer</strong>
            </div>
            <div>
                <button class="action-btn" onclick="window.print()">Print / Save as PDF</button>
                <button class="action-btn secondary" onclick="downloadStandaloneHTML()">Save Standalone HTML</button>
            </div>
        </div>
        <div class="report-header">
            <div>
                <h1>{html_lib.escape(title)}</h1>
                <p>{html_lib.escape(subtitle)}</p>
            </div>
            <div class="mono" style="text-align: right; font-size: 11px; color: #605E5C;">
                <div>Generated: {now_str}</div>
                <div>System: SCIA Magna 200</div>
            </div>
        </div>
        {body_html}
    </div>
</body>
</html>"""


def generate_run_section_html(
    run_name: str,
    selected_modules: list[str] | None,
    layout_mode: str,
    x_col: str,
    y_cols: list[str],
    pressure_mode: str,
    toggle_steps: list[str],
    expanded_substeps: list[str],
) -> str:
    run_dir = LOGS_BASE_DIR / run_name
    run_meta = parse_run_data_sav(run_dir)

    if not selected_modules:
        selected_modules = get_active_modules_for_run(run_dir)

    loaded_data = {}
    all_dates = []
    for mod in selected_modules:
        mod_path = run_dir if mod == "." else (run_dir / mod)
        df, df_steps = load_scia_module_data(mod_path)
        if not df.empty:
            loaded_data[mod] = (df, df_steps)
            if "DateTime" in df.columns:
                valid_dt = df["DateTime"].dropna()
                if not valid_dt.empty:
                    all_dates.append(valid_dt.min())

    global_t0 = min(all_dates) if all_dates else None
    for mod, (df, df_steps) in loaded_data.items():
        if global_t0 is not None and "DateTime" in df.columns:
            df["Total_ElapsedTime_s"] = (
                df["DateTime"] - global_t0
            ).dt.total_seconds()
        if (
            global_t0 is not None
            and not df_steps.empty
            and "StartDateTime" in df_steps.columns
        ):
            df_steps["ElapsedTime_s"] = (
                df_steps["StartDateTime"] - global_t0
            ).dt.total_seconds()

    if global_t0 is not None:
        date_prefix = global_t0.strftime("%Y-%m-%d")
        for t_key in ["Start Time", "End Time"]:
            val = run_meta.get(t_key, "Unknown")
            if val != "Unknown" and not re.search(
                r"\d{4}[-/]\d{2}[-/]\d{2}", val
            ):
                run_meta[t_key] = f"{date_prefix} {val}"

    expanded_by_mod = {}
    for item in expanded_substeps or []:
        if "|" in str(item):
            mod_part, step_part = str(item).split("|", 1)
            expanded_by_mod.setdefault(mod_part, []).append(step_part)
        else:
            for mod in selected_modules:
                expanded_by_mod.setdefault(mod, []).append(str(item))

    meta_html = f"""
    <div class="section-card">
        <h2 class="section-title">Run Metadata  |  {html_lib.escape(run_name)}</h2>
        <div class="meta-grid">
            <div class="meta-box"><div class="label">Lot ID</div><div class="value">{html_lib.escape(run_meta.get('Lot ID', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Wafer ID</div><div class="value">{html_lib.escape(run_meta.get('Wafer ID', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Global Sequence</div><div class="value">{html_lib.escape(run_meta.get('Sequence Name', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Operator (User)</div><div class="value">{html_lib.escape(run_meta.get('User', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Start Date & Time</div><div class="value">{html_lib.escape(run_meta.get('Start Time', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">End Date & Time</div><div class="value">{html_lib.escape(run_meta.get('End Time', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Source Station</div><div class="value">{html_lib.escape(run_meta.get('Source Station', 'Unknown'))}</div></div>
            <div class="meta-box"><div class="label">Cassette Slot</div><div class="value">{html_lib.escape(run_meta.get('Source Slot', 'Unknown'))}</div></div>
        </div>
    </div>
    """

    if not loaded_data:
        return meta_html

    if layout_mode == "overlaid":
        ignore_cols = {
            "Time",
            "DateTime",
            "StepNo",
            "RecipeName",
            "User",
            "Total_ElapsedTime_s",
        }
        all_avail_num = set()
        for df, _ in loaded_data.values():
            all_avail_num.update([
                c
                for c in df.columns
                if c not in ignore_cols and pd.api.types.is_numeric_dtype(df[c])
            ])
        active_y = [c for c in (y_cols or []) if c in all_avail_num]
        if not active_y and all_avail_num:
            active_y = sorted(all_avail_num)[:3]

        fig_over = build_overlaid_plot(
            loaded_data=loaded_data,
            x_col=x_col,
            y_cols=active_y,
            toggle_steps=toggle_steps,
            expanded_by_mod=expanded_by_mod,
            pressure_mode=pressure_mode,
        )
        fig_over.update_layout(height=430, title="")
        plot_div = fig_over.to_html(
            full_html=False,
            include_plotlyjs=False,
            config={"responsive": True, "displaylogo": False},
        )

        mod_details_html = []
        for mod, (df, df_steps) in loaded_data.items():
            mod_display = "Main Chamber" if mod == "." else mod
            recipe_name = (
                df["RecipeName"].dropna().iloc[0]
                if not df["RecipeName"].dropna().empty
                else "Unknown"
            )
            real_pts = int(df["StepNo"].dropna().count())
            total_steps = (
                df_steps["Sequence"].dropna().nunique()
                if not df_steps.empty and "Sequence" in df_steps.columns
                else df["StepNo"].dropna().nunique()
            )
            stats_html = build_stats_table_html(df, active_y)
            steps_html = build_recipe_steps_table_html(df_steps)

            mod_details_html.append(f"""
                <div style="margin-top: 16px; border-top: 1px solid #E1DFDD; padding-top: 12px;">
                    <h3 style="font-size:13px; margin:0 0 6px 0; color:#181B1F;">
                        {html_lib.escape(mod_display)}  |  Recipe: <span class="mono">{html_lib.escape(str(recipe_name))}</span>
                        <span style="font-weight:normal; font-size:11.5px; color:#605E5C;">
                            ({real_pts:,} pts, {total_steps} steps)
                        </span>
                    </h3>
                    <h4 style="font-size:11.5px; text-transform:uppercase; margin:10px 0 4px 0; color:#323130;">Channel Statistics Summary ({html_lib.escape(mod_display)})</h4>
                    {stats_html}
                    <h4 style="font-size:11.5px; text-transform:uppercase; margin:12px 0 4px 0; color:#323130;">Chronological Recipe Steps & Substeps ({html_lib.escape(mod_display)})</h4>
                    {steps_html}
                </div>
            """)

        overlaid_card = f"""
        <div class="section-card">
            <h2 class="section-title">Overlaid Process Comparison ({html_lib.escape(', '.join(['Main Chamber' if k == '.' else k for k in loaded_data.keys()]))})</h2>
            <div class="plot-wrapper">{plot_div}</div>
            {''.join(mod_details_html)}
        </div>
        """
        return meta_html + overlaid_card

    modules_html = []
    for mod, (df, df_steps) in loaded_data.items():
        mod_display = "Main Chamber" if mod == "." else mod
        ignore_cols = {
            "Time",
            "DateTime",
            "StepNo",
            "RecipeName",
            "User",
            "Total_ElapsedTime_s",
        }
        avail_num = [
            c
            for c in df.columns
            if c not in ignore_cols and pd.api.types.is_numeric_dtype(df[c])
        ]
        active_y = [c for c in (y_cols or []) if c in avail_num]
        if not active_y and avail_num:
            active_y = avail_num[:3]

        fig = build_single_plot(
            df=df,
            df_steps=df_steps,
            x_col=x_col if x_col in df.columns else "Total_ElapsedTime_s",
            y_cols=active_y,
            toggle_steps=toggle_steps,
            expanded_steps=expanded_by_mod.get(mod, []),
            pressure_mode=pressure_mode,
        )
        fig.update_layout(height=400, title="")
        plot_div = fig.to_html(
            full_html=False,
            include_plotlyjs=False,
            config={"responsive": True, "displaylogo": False},
        )

        recipe_name = (
            df["RecipeName"].dropna().iloc[0]
            if not df["RecipeName"].dropna().empty
            else "Unknown"
        )
        real_pts = int(df["StepNo"].dropna().count())
        total_steps = (
            df_steps["Sequence"].dropna().nunique()
            if not df_steps.empty and "Sequence" in df_steps.columns
            else df["StepNo"].dropna().nunique()
        )

        stats_html = build_stats_table_html(df, active_y)
        steps_html = build_recipe_steps_table_html(df_steps)

        modules_html.append(f"""
        <div class="section-card">
            <h2 class="section-title">{html_lib.escape(mod_display)}  |  Recipe: {html_lib.escape(str(recipe_name))}</h2>
            <p style="font-size:11.5px; color:#605E5C; margin:0 0 8px 0;">
                <strong>Recorded Points:</strong> <span class="mono">{real_pts:,}</span> &nbsp;|&nbsp;
                <strong>Main Steps:</strong> <span class="mono">{total_steps}</span>
            </p>
            <div class="plot-wrapper">{plot_div}</div>
            <h3 style="font-size:12px; text-transform:uppercase; margin:14px 0 6px 0; color:#323130; page-break-after:avoid; break-after:avoid;">Channel Statistics Summary</h3>
            {stats_html}
            <h3 style="font-size:12px; text-transform:uppercase; margin:16px 0 6px 0; color:#323130; page-break-after:avoid; break-after:avoid;">Chronological Recipe Steps & Substeps</h3>
            {steps_html}
        </div>
        """)

    return meta_html + "\n".join(modules_html)


# --- Aplicação Dash ---
app = Dash(__name__)
app.title = "SCIA Magna 200 | Process Log Analyzer"


@app.server.route("/reports/<path:filename>")
def serve_generated_report(filename: str):
    return flask.send_from_directory(REPORTS_DIR, filename)


app.index_string = """
<!DOCTYPE html>
<html>
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            * {
                box-sizing: border-box;
            }
            body {
                margin: 0;
                padding: 0;
                background-color: #F3F2F1;
                color: #201F1E;
                font-family: 'Inter', 'Segoe UI', -apple-system, Arial, sans-serif;
            }
            /* Cartões de Filtro estilo Power BI */
            .pbi-card {
                background-color: #FAF9F8;
                border: 1px solid #E1DFDD;
                border-radius: 2px;
                padding: 10px 12px;
            }
            .pbi-section-header {
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                color: #323130;
                margin-bottom: 8px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #EDEBE9;
                padding-bottom: 5px;
            }
            .pbi-field-label {
                font-size: 11.5px;
                font-weight: 600;
                color: #323130;
                display: inline-block;
                margin-bottom: 3px;
            }
            /* Ajustes nos Dropdowns do Dash para cantos retos estilo Power BI */
            .Select-control {
                border-radius: 2px !important;
                border: 1px solid #C8C6C4 !important;
                font-size: 12px !important;
                min-height: 32px !important;
            }
            .Select-control:hover {
                border-color: #605E5C !important;
            }
            /* Full Screen Plot Card */
            .plot-card:fullscreen {
                background-color: #ffffff !important;
                width: 100vw !important;
                height: 100vh !important;
                padding: 20px !important;
                box-sizing: border-box !important;
                display: flex !important;
                flex-direction: column !important;
                z-index: 999999 !important;
            }
            .plot-card:fullscreen .dash-graph,
            .plot-card:fullscreen .js-plotly-plot {
                height: calc(100vh - 65px) !important;
                flex: 1 !important;
            }
            .btn-fs-toggle {
                transition: all 0.12s ease-in-out;
                font-family: 'Inter', 'Segoe UI', sans-serif;
            }
            .btn-fs-toggle:hover {
                background-color: #181B1F !important;
                color: #ffffff !important;
                border-color: #181B1F !important;
            }
            /* Botões de Ajuda Contextual (?) discretos estilo técnico */
            .help-badge {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 14px;
                height: 14px;
                border-radius: 2px;
                background-color: #EDEBE9;
                border: 1px solid #C8C6C4;
                color: #605E5C;
                font-size: 10px;
                font-weight: 700;
                margin-left: 5px;
                cursor: pointer;
                user-select: none;
                vertical-align: middle;
            }
            .help-badge:hover {
                background-color: #0078D4;
                border-color: #0078D4;
                color: #FFFFFF;
            }
            /* Popover de Ajuda estilo Grafana Dark */
            #global-help-popover {
                position: fixed;
                display: none;
                max-width: 300px;
                background-color: #181B1F;
                color: #F3F2F1;
                padding: 8px 12px;
                border-radius: 2px;
                font-size: 11.5px;
                line-height: 1.45;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                z-index: 1000000;
                pointer-events: none;
                border: 1px solid #3C444D;
                border-left: 3px solid #0078D4;
            }
            /* Modal do Manual de Utilizador */
            #user-manual-modal {
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                background-color: rgba(24, 27, 31, 0.7);
                display: none;
                align-items: center;
                justify-content: center;
                z-index: 999998;
                padding: 24px;
                box-sizing: border-box;
            }
            .manual-content {
                background: #FFFFFF;
                max-width: 860px;
                width: 100%;
                max-height: 88vh;
                border-radius: 2px;
                border: 1px solid #3C444D;
                box-shadow: 0 12px 32px rgba(0,0,0,0.35);
                display: flex;
                flex-direction: column;
                overflow: hidden;
            }
            .manual-header {
                padding: 14px 20px;
                background: #181B1F;
                color: #F3F2F1;
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 2px solid #0078D4;
            }
            .manual-body {
                padding: 20px 24px;
                overflow-y: auto;
                font-size: 13px;
                line-height: 1.55;
                color: #323130;
            }
            .manual-body h3 {
                color: #181B1F;
                margin-top: 18px;
                margin-bottom: 6px;
                font-size: 13.5px;
                text-transform: uppercase;
                letter-spacing: 0.3px;
                border-left: 3px solid #0078D4;
                padding-left: 8px;
            }
            .manual-body ul {
                margin-top: 4px;
                padding-left: 18px;
            }
            .manual-body li {
                margin-bottom: 6px;
            }
            .manual-badge {
                background: #F3F2F1;
                color: #201F1E;
                border: 1px solid #C8C6C4;
                padding: 1px 6px;
                border-radius: 2px;
                font-weight: 600;
                font-size: 11.5px;
                font-family: 'IBM Plex Mono', Consolas, monospace;
            }
        </style>
        <script>
            document.addEventListener('click', function(e) {
                const fsBtn = e.target.closest('.btn-fs-toggle');
                if (fsBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const card = fsBtn.closest('.plot-card');
                    if (!card) return;

                    if (!document.fullscreenElement) {
                        if (card.requestFullscreen) card.requestFullscreen();
                        else if (card.webkitRequestFullscreen) card.webkitRequestFullscreen();
                    } else {
                        if (document.exitFullscreen) document.exitFullscreen();
                        else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
                    }
                    setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 200);
                    return;
                }

                const openManualBtn = e.target.closest('#btn-open-manual');
                if (openManualBtn) {
                    const modal = document.getElementById('user-manual-modal');
                    if (modal) modal.style.display = 'flex';
                    return;
                }

                if (e.target.closest('#btn-close-manual') || e.target.id === 'user-manual-modal') {
                    const modal = document.getElementById('user-manual-modal');
                    if (modal) modal.style.display = 'none';
                    return;
                }
            });

            document.addEventListener('keydown', function(e) {
                if (e.key === 'Escape') {
                    const modal = document.getElementById('user-manual-modal');
                    if (modal && modal.style.display === 'flex') {
                        modal.style.display = 'none';
                    }
                }
            });

            document.addEventListener('fullscreenchange', function() {
                setTimeout(function() { window.dispatchEvent(new Event('resize')); }, 150);
            });

            document.addEventListener('DOMContentLoaded', function() {
                const popover = document.createElement('div');
                popover.id = 'global-help-popover';
                document.body.appendChild(popover);

                function showHelp(badge) {
                    const text = badge.getAttribute('data-help');
                    if (!text) return;
                    popover.textContent = text;
                    popover.style.display = 'block';

                    const rect = badge.getBoundingClientRect();
                    let left = rect.right + 10;
                    let top = rect.top - 6;

                    if (left + 310 > window.innerWidth) {
                        left = Math.max(10, rect.left - 310);
                    }
                    if (top + popover.offsetHeight > window.innerHeight - 10) {
                        top = Math.max(10, window.innerHeight - popover.offsetHeight - 15);
                    }
                    popover.style.left = left + 'px';
                    popover.style.top = top + 'px';
                }

                function hideHelp() {
                    popover.style.display = 'none';
                }

                document.body.addEventListener('mouseover', function(e) {
                    const badge = e.target.closest('.help-badge');
                    if (badge) showHelp(badge);
                });

                document.body.addEventListener('mouseout', function(e) {
                    const badge = e.target.closest('.help-badge');
                    if (badge) hideHelp();
                });

                document.body.addEventListener('click', function(e) {
                    const badge = e.target.closest('.help-badge');
                    if (badge) {
                        e.preventDefault();
                        e.stopPropagation();
                        if (popover.style.display === 'block') hideHelp();
                        else showHelp(badge);
                    } else {
                        hideHelp();
                    }
                });

                let lastOpenedUrl = "";
                const obs = new MutationObserver(function() {
                    const urlNode = document.getElementById('report-open-url');
                    if (urlNode && urlNode.textContent) {
                        const url = urlNode.textContent.trim();
                        if (url && url !== lastOpenedUrl) {
                            lastOpenedUrl = url;
                            window.open(url, '_blank');
                        }
                    }
                });
                obs.observe(document.body, { childList: true, subtree: true, characterData: true });
            });
        </script>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
"""

app.layout = html.Div(
    style={
        "minHeight": "100vh",
        "display": "flex",
        "flexDirection": "column",
        "backgroundColor": "#F3F2F1",
    },
    children=[
        #Manual de Utilizador
        html.Div(
            id="user-manual-modal",
            children=[
                html.Div(
                    className="manual-content",
                    children=[
                        html.Div(
                            className="manual-header",
                            children=[
                                html.Div([
                                    html.H2(
                                        "SCIA Magna 200  /  Documentation & User Guide",
                                        style={"margin": "0", "fontSize": "15px", "fontWeight": "600"},
                                    ),
                                ]),
                                html.Button(
                                    "Close [Esc]",
                                    id="btn-close-manual",
                                    style={
                                        "background": "#2C3235",
                                        "color": "#F3F2F1",
                                        "border": "1px solid #484644",
                                        "padding": "5px 12px",
                                        "borderRadius": "2px",
                                        "cursor": "pointer",
                                        "fontWeight": "600",
                                        "fontSize": "12px",
                                    },
                                ),
                            ],
                        ),
                        html.Div(
                            className="manual-body",
                            children=[
                                html.H3("Process Hierarchy (Lot ID, Wafer ID, and Run)"),
                                html.Ul([
                                    html.Li([
                                        html.Span("Lot ID", className="manual-badge"),
                                        " Identifies the fabrication batch. Leaving it empty displays all lots.",
                                    ]),
                                    html.Li([
                                        html.Span("Wafer ID", className="manual-badge"),
                                        " Identifies the specific physical substrate inside a lot. Selecting a Wafer filters all runs performed on that substrate.",
                                    ]),
                                    html.Li([
                                        html.Span("Run (Log)", className="manual-badge"),
                                        " Selects the specific timestamped machine execution folder.",
                                    ]),
                                ]),
                                html.H3("Process Modules & Multi-Module Layout"),
                                html.Ul([
                                    html.Li([
                                        html.Span("Process Module(s)", className="manual-badge"),
                                        " The SCIA Magna 200 is a cluster tool with separate vacuum chambers (Process Module 1 & Process Module 2). Empty module folders are automatically filtered out.",
                                    ]),
                                    html.Li([
                                        html.Span("Stacked (Separate Plots)", className="manual-badge"),
                                        " Displays one dedicated chart per chamber vertically.",
                                    ]),
                                    html.Li([
                                        html.Span("Overlaid (Single Plot)", className="manual-badge"),
                                        " Synchronizes all selected chambers on a global continuous timeline and plots them together, labeling each step with its module.",
                                    ]),
                                ]),
                                html.H3("Trend Profiles (Channel Presets)"),
                                html.Ul([
                                    html.Li("Choose from built-in engineering presets (Overview, Vacuum & Pumping, Gas System, DC Sputtering, Substrate RF Bias) to quickly load relevant sensors."),
                                    html.Li("To create a custom profile: select your desired channels in the Y Parameters box, type a name in 'New profile name...', and click Save. It will be stored permanently."),
                                ]),
                                html.H3("Axes, Units & Pressure Scale Mode"),
                                html.Ul([
                                    html.Li([
                                        html.Span("Multi-Axis Grouping", className="manual-badge"),
                                        " Channels sharing the same physical unit ([mbar], [sccm], [W], [V]) are automatically grouped onto calibrated color-coded vertical axes.",
                                    ]),
                                    html.Li([
                                        html.Span("Log Scale & SI Prefixes", className="manual-badge"),
                                        " Vacuum pressure spans several orders of magnitude (from 10⁻⁷ mbar base vacuum to 10⁻³ mbar sputtering pressure). In Log mode, Plotly uses standard SI prefixes: ",
                                        html.Strong("m"), " = 10⁻³ mbar, ",
                                        html.Strong("µ"), " = 10⁻⁶ mbar, and ",
                                        html.Strong("n"), " = 10⁻⁹ mbar (e.g., 220n mbar = 2.2 × 10⁻⁷ mbar).",
                                    ]),
                                ]),
                                html.H3("Step Boundaries & Substeps"),
                                html.Ul([
                                    html.Li([
                                        html.Span("Show main step boundaries", className="manual-badge"),
                                        " Highlights each main recipe step on the chart with a shaded region and vertical dashed lines marking the start and end of the step.",
                                    ]),
                                    html.Li([
                                        html.Span("Expand substeps", className="manual-badge"),
                                        " Overlays dotted vertical lines for every internal PLC command executed inside the selected step(s), such as gas flows, shutter open/close, and power changes.",
                                    ]),
                                ]),
                                html.H3("Full Screen & Reports (PDF vs. Interactive HTML)"),
                                html.Ul([
                                    html.Li([
                                        html.Span("Full Screen", className="manual-badge"),
                                        " Located in the top-right corner of every plot card. Expands the chart to 100% of your screen (press Esc to exit).",
                                    ]),
                                    html.Li([
                                        html.Span("Run Report", className="manual-badge"),
                                        " Generates a complete report for the active run, respecting your chosen layout mode (Stacked or Overlaid), including metadata, charts, Min/Max/Mean/StdDev statistics, and the chronological step table.",
                                    ]),
                                    html.Li([
                                        html.Span("Wafer History", className="manual-badge"),
                                        " Automatically finds all runs performed on the selected Wafer ID, builds a chronological summary timeline, and compiles all run reports into a single document.",
                                    ]),
                                    html.Li([
                                        html.Span("PDF vs. Interactive HTML", className="manual-badge"),
                                        " Inside the report viewer, ",
                                        html.Strong("Print / Save as PDF"),
                                        " creates a static A4 document ideal for printing or formal archiving, while ",
                                        html.Strong("Save Standalone HTML"),
                                        " saves a standalone web file that preserves full chart interactivity (zoom, pan, and hover values) on any computer without requiring Python.",
                                    ]),
                                ]),
                            ],
                        ),
                    ],
                )
            ],
        ),
        # Barra de Topo Escura (Inspirada no Grafana)
        html.Div(
            style={
                "backgroundColor": "#181B1F",
                "color": "#F3F2F1",
                "height": "46px",
                "padding": "0 20px",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
                "borderBottom": "1px solid #2C3235",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "10px"},
                    children=[
                        html.Span(
                            style={
                                "width": "8px",
                                "height": "18px",
                                "backgroundColor": "#0078D4",
                                "display": "inline-block",
                                "borderRadius": "1px",
                            }
                        ),
                        html.Span(
                            "SCIA Magna 200",
                            style={"fontWeight": "700", "fontSize": "14px", "letterSpacing": "0.2px"},
                        ),
                    ],
                ),
                html.Button(
                    "User Manual",
                    id="btn-open-manual",
                    style={
                        "backgroundColor": "#0078D4",
                        "color": "#FFFFFF",
                        "border": "1px solid #005A9E",
                        "padding": "5px 14px",
                        "borderRadius": "2px",
                        "fontSize": "12px",
                        "fontWeight": "600",
                        "cursor": "pointer",
                    },
                ),
            ],
        ),
        # Corpo Principal
        html.Div(
            style={"display": "flex", "flex": "1", "gap": "16px", "padding": "16px"},
            children=[
                # Painel de Filtros Esquerdo 
                html.Div(
                    style={
                        "width": "330px",
                        "minWidth": "330px",
                        "display": "flex",
                        "flexDirection": "column",
                        "gap": "10px",
                        "backgroundColor": "#FFFFFF",
                        "padding": "12px",
                        "border": "1px solid #E1DFDD",
                        "borderRadius": "2px",
                    },
                    children=[
                        # Cartão: Data Source & Hierarchy
                        html.Div(
                            className="pbi-card",
                            children=[
                                html.Div(
                                    className="pbi-section-header",
                                    children=[
                                        html.Div([
                                            html.Span("Process Hierarchy"),
                                            help_badge(
                                                "Filter logs hierarchically by fabrication Lot ID, individual Wafer ID, or select a specific timestamped Run directly."
                                            ),
                                        ]),
                                        html.Button(
                                            "Refresh",
                                            id="btn-refresh-runs",
                                            n_clicks=0,
                                            title="Rescan SCIA logs folder for new runs",
                                            style={
                                                "fontSize": "11px",
                                                "padding": "2px 8px",
                                                "backgroundColor": "#FFFFFF",
                                                "color": "#323130",
                                                "border": "1px solid #C8C6C4",
                                                "borderRadius": "2px",
                                                "cursor": "pointer",
                                                "fontWeight": "600",
                                            },
                                        ),
                                    ],
                                ),
                                html.Div([
                                    html.Label("Lot ID", className="pbi-field-label"),
                                    help_badge(
                                        "Select a batch Lot ID to show only wafers and runs from that lot. Leave empty to show all lots."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-lot",
                                    clearable=True,
                                    placeholder="All Lots",
                                    style={"marginBottom": "8px"},
                                ),
                                html.Div([
                                    html.Label("Wafer ID", className="pbi-field-label"),
                                    help_badge(
                                        "Filter runs by a specific physical Wafer ID. Useful when a wafer undergoes multiple sequential runs."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-wafer",
                                    clearable=True,
                                    placeholder="All Wafers",
                                    style={"marginBottom": "8px"},
                                ),
                                html.Div([
                                    html.Label("Run Log", className="pbi-field-label"),
                                    help_badge(
                                        "Select the specific process run folder to visualize on the dashboard."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-run",
                                    clearable=False,
                                    placeholder="Select run...",
                                ),
                            ],
                        ),
                        # Cartão: Chamber & Layout Configuration
                        html.Div(
                            className="pbi-card",
                            children=[
                                html.Div(
                                    className="pbi-section-header",
                                    children=[
                                        html.Span("Chamber Configuration"),
                                    ],
                                ),
                                html.Div([
                                    html.Label("Process Module(s)", className="pbi-field-label"),
                                    help_badge(
                                        "Select which active vacuum chamber(s) (Process Module 1 and/or Process Module 2) to display."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-module",
                                    multi=True,
                                    clearable=False,
                                    style={"marginBottom": "8px"},
                                ),
                                html.Div([
                                    html.Label("Multi-Module Layout", className="pbi-field-label"),
                                    help_badge(
                                        "Stacked shows separate vertical charts for each module. Overlaid merges all modules onto a single synchronized timeline."
                                    ),
                                ]),
                                dcc.RadioItems(
                                    id="layout-mode",
                                    options=[
                                        {
                                            "label": " Stacked (Separate Plots)",
                                            "value": "stacked",
                                        },
                                        {
                                            "label": " Overlaid (Single Plot)",
                                            "value": "overlaid",
                                        },
                                    ],
                                    value="stacked",
                                    inline=False,
                                    style={
                                        "fontSize": "12px",
                                        "display": "flex",
                                        "flexDirection": "column",
                                        "gap": "4px",
                                        "marginTop": "2px",
                                    },
                                ),
                            ],
                        ),
                        # Cartão: Channels, Presets & Scales
                        html.Div(
                            className="pbi-card",
                            children=[
                                html.Div(
                                    className="pbi-section-header",
                                    children=[
                                        html.Span("Channels & Axes"),
                                    ],
                                ),
                                html.Div([
                                    html.Label("Trend Profile", className="pbi-field-label"),
                                    help_badge(
                                        "Quickly load predefined channel combinations (Overview, Vacuum, Gas System, DC Sputtering, RF Bias) or save your own custom preset."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-profile",
                                    clearable=True,
                                    placeholder="Select preset...",
                                ),
                                html.Div(
                                    style={
                                        "display": "flex",
                                        "gap": "6px",
                                        "marginTop": "6px",
                                        "marginBottom": "8px",
                                    },
                                    children=[
                                        dcc.Input(
                                            id="new-profile-name",
                                            type="text",
                                            placeholder="Save current channels as...",
                                            style={
                                                "flex": "1",
                                                "fontSize": "11.5px",
                                                "padding": "4px 8px",
                                                "border": "1px solid #C8C6C4",
                                                "borderRadius": "2px",
                                            },
                                        ),
                                        html.Button(
                                            "Save",
                                            id="btn-save-profile",
                                            n_clicks=0,
                                            style={
                                                "fontSize": "11.5px",
                                                "padding": "4px 10px",
                                                "backgroundColor": "#323130",
                                                "color": "white",
                                                "border": "none",
                                                "borderRadius": "2px",
                                                "cursor": "pointer",
                                                "fontWeight": "600",
                                            },
                                        ),
                                    ],
                                ),
                                html.Div(
                                    id="profile-msg",
                                    style={
                                        "fontSize": "11px",
                                        "color": "#107C10",
                                        "marginBottom": "4px",
                                    },
                                ),
                                html.Div([
                                    html.Label("X-Axis", className="pbi-field-label"),
                                    help_badge(
                                        "Plot data against relative elapsed time in seconds (from run start t0 = 0s) or absolute wall-clock Date/Time."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-x",
                                    options=[
                                        {
                                            "label": "Total Elapsed Time (s)",
                                            "value": "Total_ElapsedTime_s",
                                        },
                                        {
                                            "label": "Date / Time",
                                            "value": "DateTime",
                                        },
                                    ],
                                    value="Total_ElapsedTime_s",
                                    clearable=False,
                                    style={"marginBottom": "8px"},
                                ),
                                html.Div([
                                    html.Label("Y Parameters (Channels)", className="pbi-field-label"),
                                    help_badge(
                                        "Select one or more physical sensor channels. Channels with different units ([mbar], [sccm], [W]) are automatically placed on separate Y axes."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-y",
                                    multi=True,
                                    placeholder="Select channels...",
                                    style={"marginBottom": "8px"},
                                ),
                                html.Div([
                                    html.Label("Pressure Scale Mode", className="pbi-field-label"),
                                    help_badge(
                                        "Switch pressure axes between Logarithmic scale and Linear scale."
                                    ),
                                ]),
                                dcc.RadioItems(
                                    id="pressure-mode",
                                    options=[
                                        {"label": " Log Scale", "value": "log"},
                                        {"label": " Linear Scale", "value": "linear"},
                                    ],
                                    value="log",
                                    inline=True,
                                    style={
                                        "fontSize": "12px",
                                        "gap": "14px",
                                        "display": "flex",
                                        "marginTop": "2px",
                                    },
                                ),
                            ],
                        ),
                        # Cartão: Step Overlays
                        html.Div(
                            className="pbi-card",
                            children=[
                                html.Div(
                                    className="pbi-section-header",
                                    children=[
                                        html.Span("Recipe Step Overlays"),
                                    ],
                                ),
                                html.Div(
                                    style={"display": "flex", "alignItems": "center", "marginBottom": "8px"},
                                    children=[
                                        dcc.Checklist(
                                            id="toggle-steps",
                                            options=[
                                                {
                                                    "label": " Show main step boundaries",
                                                    "value": "show",
                                                }
                                            ],
                                            value=["show"],
                                            style={"fontSize": "12px", "display": "inline-block"},
                                        ),
                                        help_badge(
                                            "Highlights each recipe step with a shaded region and dashed start/end lines based on timestamps."
                                        ),
                                    ],
                                ),
                                html.Div([
                                    html.Label("Expand Substeps", className="pbi-field-label"),
                                    help_badge(
                                        "Displays vertical dotted lines for every internal PLC command (gas flows, shutter actions, power changes) inside the selected step(s)."
                                    ),
                                ]),
                                dcc.Dropdown(
                                    id="select-substeps",
                                    multi=True,
                                    placeholder="Select steps to expand...",
                                ),
                            ],
                        ),
                        # Cartão: Reports & Export
                        html.Div(
                            className="pbi-card",
                            children=[
                                html.Div(
                                    className="pbi-section-header",
                                    children=[
                                        html.Div([
                                            html.Span("Reports & Export"),
                                            help_badge(
                                                "Generate printable A4 PDF reports or standalone interactive HTML files."
                                            ),
                                        ]),
                                    ],
                                ),
                                html.Div(
                                    style={
                                        "display": "flex",
                                        "flexDirection": "column",
                                        "gap": "6px",
                                    },
                                    children=[
                                        html.Div(
                                            style={"display": "flex", "alignItems": "center"},
                                            children=[
                                                html.Button(
                                                    "Export Run Report (PDF / HTML)",
                                                    id="btn-run-report",
                                                    n_clicks=0,
                                                    style={
                                                        "flex": "1",
                                                        "fontSize": "11.5px",
                                                        "padding": "7px 10px",
                                                        "backgroundColor": "#0078D4",
                                                        "color": "white",
                                                        "border": "1px solid #005A9E",
                                                        "borderRadius": "2px",
                                                        "cursor": "pointer",
                                                        "fontWeight": "600",
                                                        "textAlign": "left",
                                                    },
                                                ),
                                                help_badge(
                                                    "Creates a complete report for the currently selected Run, including metadata, interactive chart(s), channel statistics (Min/Max/Mean/StdDev), and recipe step tables."
                                                ),
                                            ],
                                        ),
                                        html.Div(
                                            style={"display": "flex", "alignItems": "center"},
                                            children=[
                                                html.Button(
                                                    "Export Wafer History (All Runs)",
                                                    id="btn-wafer-report",
                                                    n_clicks=0,
                                                    style={
                                                        "flex": "1",
                                                        "fontSize": "11.5px",
                                                        "padding": "7px 10px",
                                                        "backgroundColor": "#2C3235",
                                                        "color": "white",
                                                        "border": "1px solid #181B1F",
                                                        "borderRadius": "2px",
                                                        "cursor": "pointer",
                                                        "fontWeight": "600",
                                                        "textAlign": "left",
                                                    },
                                                ),
                                                help_badge(
                                                    "Tracks all runs performed on the current Wafer ID in chronological order, generating a master timeline table followed by detailed plots and logs for every run."
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                html.Div(
                                    id="report-status-msg",
                                    style={
                                        "marginTop": "6px",
                                        "fontSize": "11.5px",
                                    },
                                ),
                                html.Div(
                                    id="report-open-url",
                                    style={"display": "none"},
                                ),
                            ],
                        ),
                        # Cartão: Run Summary Readout
                        html.Div(
                            id="run-metadata-card",
                            className="pbi-card",
                            style={
                                "fontSize": "11px",
                                "lineHeight": "1.5",
                                "color": "#323130",
                            },
                        ),
                    ],
                ),
                # Área Principal de Gráficos
                html.Div(
                    style={"flex": "1"},
                    children=[
                        dcc.Loading(
                            type="dot",
                            color="#0078D4",
                            children=html.Div(id="plots-container"),
                        )
                    ],
                ),
            ],
        ),
    ],
)


# --- Callbacks ---


@app.callback(
    Output("select-lot", "options"),
    Output("select-wafer", "options"),
    Output("select-wafer", "value"),
    Input("select-lot", "value"),
    Input("btn-refresh-runs", "n_clicks"),
    State("select-wafer", "value"),
)
def update_hierarchy_filters(selected_lot, _n_refresh, current_wafer):
    catalog = get_runs_catalog()
    if catalog.empty:
        return [], [], None

    all_lots = sorted([
        x for x in catalog["Lot"].dropna().unique() if x and x != "Unknown"
    ])
    lot_options = [{"label": l, "value": l} for l in all_lots]

    df_filtered = catalog.copy()
    if selected_lot:
        df_filtered = df_filtered[df_filtered["Lot"] == selected_lot]

    available_wafers = sorted([
        x for x in df_filtered["Wafer"].dropna().unique() if x
    ])
    wafer_options = [{"label": w, "value": w} for w in available_wafers]

    new_wafer_val = current_wafer if current_wafer in available_wafers else None
    return lot_options, wafer_options, new_wafer_val


@app.callback(
    Output("select-run", "options"),
    Output("select-run", "value"),
    Input("select-lot", "value"),
    Input("select-wafer", "value"),
    Input("btn-refresh-runs", "n_clicks"),
    State("select-run", "value"),
)
def update_runs_dropdown(selected_lot, selected_wafer, _n_refresh, current_run):
    catalog = get_runs_catalog()
    if catalog.empty:
        return [], None

    df_filtered = catalog.copy()
    if selected_lot:
        df_filtered = df_filtered[df_filtered["Lot"] == selected_lot]
    if selected_wafer:
        df_filtered = df_filtered[df_filtered["Wafer"] == selected_wafer]

    available_runs = sorted(df_filtered["Run"].unique())
    run_options = [{"label": r, "value": r} for r in available_runs]
    new_run = (
        current_run
        if current_run in available_runs
        else (available_runs[0] if available_runs else None)
    )
    return run_options, new_run


@app.callback(
    Output("select-module", "options"),
    Output("select-module", "value"),
    Input("select-run", "value"),
)
def update_modules(selected_run):
    if not selected_run:
        return [], []
    run_path = LOGS_BASE_DIR / selected_run
    active_modules = get_active_modules_for_run(run_path)
    options = [
        {"label": "Main Chamber" if m == "." else m, "value": m}
        for m in active_modules
    ]
    return options, active_modules


@app.callback(
    Output("select-profile", "options"),
    Output("select-profile", "value"),
    Output("profile-msg", "children"),
    Input("btn-save-profile", "n_clicks"),
    State("new-profile-name", "value"),
    State("select-y", "value"),
    prevent_initial_call=False,
)
def manage_profiles(n_clicks, new_name, current_y):
    ctx = dash.callback_context
    profiles = load_trend_profiles()
    msg = ""

    if (
        ctx.triggered
        and ctx.triggered[0]["prop_id"] == "btn-save-profile.n_clicks"
    ):
        if new_name and current_y:
            profiles[new_name.strip()] = current_y
            save_all_trend_profiles(profiles)
            msg = f"Profile '{new_name}' saved."
            return (
                [{"label": k, "value": k} for k in profiles.keys()],
                new_name.strip(),
                msg,
            )
        else:
            msg = "Enter a name and select channels first."

    options = [{"label": k, "value": k} for k in profiles.keys()]
    default_profile = (
        "Overview"
        if "Overview" in profiles
        else (list(profiles.keys())[0] if profiles else None)
    )
    return options, default_profile, msg


@app.callback(
    Output("select-y", "options"),
    Output("select-y", "value"),
    Output("select-substeps", "options"),
    Output("run-metadata-card", "children"),
    Input("select-run", "value"),
    Input("select-module", "value"),
    Input("select-profile", "value"),
    State("select-y", "value"),
)
def update_parameters_and_substeps(
    selected_run, selected_modules, selected_profile, current_y
):
    if not selected_run or not selected_modules:
        return [], [], [], "No active module selected."

    if isinstance(selected_modules, str):
        selected_modules = [selected_modules]

    all_numeric_cols = set()
    substep_opts = []
    meta_cards = [
        html.Div("Run Metadata", className="pbi-section-header"),
    ]

    run_dir = LOGS_BASE_DIR / selected_run
    run_meta = parse_run_data_sav(run_dir)

    meta_cards.append(
        html.Div([html.Strong("Lot ID: "), html.Span(run_meta.get("Lot ID", "N/A"), style={"fontFamily": "'IBM Plex Mono', monospace"})])
    )
    meta_cards.append(
        html.Div([html.Strong("Wafer ID: "), html.Span(run_meta.get("Wafer ID", "N/A"), style={"fontFamily": "'IBM Plex Mono', monospace"})])
    )
    if run_meta.get("Date") != "Unknown":
        meta_cards.append(
            html.Div([html.Strong("Date: "), html.Span(run_meta.get("Date"), style={"fontFamily": "'IBM Plex Mono', monospace"})])
        )
    if run_meta.get("Sequence Name") != "Unknown":
        meta_cards.append(
            html.Div([
                html.Strong("Global Sequence: "),
                html.Span(run_meta["Sequence Name"], style={"fontFamily": "'IBM Plex Mono', monospace"}),
            ])
        )
    if run_meta.get("Source Slot") != "Unknown":
        meta_cards.append(
            html.Div(
                [html.Strong("Cassette Slot: "), html.Span(run_meta["Source Slot"], style={"fontFamily": "'IBM Plex Mono', monospace"})]
            )
        )
    meta_cards.append(
        html.Hr(style={"margin": "6px 0", "border": "none", "borderTop": "1px solid #E1DFDD"})
    )

    for mod in selected_modules:
        mod_path = run_dir if mod == "." else (run_dir / mod)
        mod_display = "Main Chamber" if mod == "." else mod
        df, df_steps = load_scia_module_data(mod_path)
        if df.empty:
            continue

        ignore_cols = {
            "Time",
            "DateTime",
            "StepNo",
            "RecipeName",
            "User",
            "Total_ElapsedTime_s",
        }
        num_cols = [
            c
            for c in df.columns
            if c not in ignore_cols and pd.api.types.is_numeric_dtype(df[c])
        ]
        all_numeric_cols.update(num_cols)

        if not df_steps.empty and "Sequence" in df_steps.columns:
            for s_val in sorted(df_steps["Sequence"].dropna().unique()):
                substep_opts.append(
                    {
                        "label": f"{mod_display} | Step {int(s_val)}",
                        "value": f"{mod}|{int(s_val)}",
                    }
                )
        else:
            valid_steps = df.dropna(subset=["StepNo"])
            for s_val in sorted(valid_steps["StepNo"].dropna().unique()):
                substep_opts.append(
                    {
                        "label": f"{mod_display} | Step {int(s_val)}",
                        "value": f"{mod}|{int(s_val)}",
                    }
                )

        recipe_name = (
            df["RecipeName"].dropna().iloc[0]
            if not df["RecipeName"].dropna().empty
            else "Unknown"
        )
        total_steps = (
            df_steps["Sequence"].dropna().nunique()
            if not df_steps.empty and "Sequence" in df_steps.columns
            else df["StepNo"].dropna().nunique()
        )
        real_pts = int(df["StepNo"].dropna().count())
        meta_cards.append(
            html.Div([
                html.Strong(f"{mod_display}: "),
                html.Span(
                    f"{recipe_name} ({real_pts:,} pts, {total_steps} steps)",
                    style={"fontFamily": "'IBM Plex Mono', monospace", "fontSize": "10.5px"},
                ),
            ])
        )

    meta_cards.append(
        html.Hr(style={"margin": "6px 0", "border": "none", "borderTop": "1px solid #E1DFDD"})
    )
    meta_cards.append(
        html.Div(
            [
                html.Strong("Source Path: "),
                html.Span(str(LOGS_BASE_DIR), style={"fontFamily": "'IBM Plex Mono', monospace"}),
            ],
            style={"fontSize": "10px", "color": "#605E5C", "wordBreak": "break-all"},
        )
    )

    options = [
        {"label": clean_column_label(c), "value": c}
        for c in sorted(all_numeric_cols)
    ]

    profiles = load_trend_profiles()
    valid_current_y = [c for c in (current_y or []) if c in all_numeric_cols]

    if selected_profile and selected_profile in profiles:
        target_cols = profiles[selected_profile]
        selected_y = [c for c in target_cols if c in all_numeric_cols]
    else:
        selected_y = valid_current_y

    if not selected_y and all_numeric_cols:
        defaults = []
        for kw in ["pressure", "flow", "power", "voltage"]:
            found = [c for c in sorted(all_numeric_cols) if kw in c.lower()]
            if found and found[0] not in defaults:
                defaults.append(found[0])
        selected_y = (
            defaults[:3] if defaults else list(sorted(all_numeric_cols))[:3]
        )

    return options, selected_y, substep_opts, meta_cards


@app.callback(
    Output("plots-container", "children"),
    Input("select-run", "value"),
    Input("select-module", "value"),
    Input("layout-mode", "value"),
    Input("select-x", "value"),
    Input("select-y", "value"),
    Input("pressure-mode", "value"),
    Input("toggle-steps", "value"),
    Input("select-substeps", "value"),
)
def render_plots(
    selected_run,
    selected_modules,
    layout_mode,
    x_col,
    y_cols,
    pressure_mode,
    toggle_steps,
    expanded_substeps,
):
    if not selected_run:
        return html.Div(
            "Select a run to begin.",
            style={"padding": "40px", "color": "#605E5C"},
        )

    run_dir = LOGS_BASE_DIR / selected_run

    if isinstance(selected_modules, str):
        selected_modules = [selected_modules]

    loaded_data = {}
    all_dates = []

    for mod in selected_modules or []:
        mod_path = run_dir if mod == "." else (run_dir / mod)
        df, df_steps = load_scia_module_data(mod_path)
        if not df.empty:
            loaded_data[mod] = (df, df_steps)
            if "DateTime" in df.columns:
                valid_dt = df["DateTime"].dropna()
                if not valid_dt.empty:
                    all_dates.append(valid_dt.min())

    if not loaded_data:
        return html.Div(
            f"No TrendData files found in {selected_run}.",
            style={"padding": "40px", "color": "#A4262C"},
        )

    if not y_cols:
        return html.Div(
            "Select at least one Y parameter (channel) to plot.",
            style={"padding": "40px", "color": "#605E5C"},
        )

    expanded_substeps = expanded_substeps or []
    expanded_by_mod = {}
    for item in expanded_substeps:
        if "|" in str(item):
            mod_part, step_part = str(item).split("|", 1)
            expanded_by_mod.setdefault(mod_part, []).append(step_part)
        else:
            for mod in selected_modules:
                expanded_by_mod.setdefault(mod, []).append(str(item))

    global_t0 = min(all_dates) if all_dates else None

    for mod, (df, df_steps) in loaded_data.items():
        if global_t0 is not None and "DateTime" in df.columns:
            df["Total_ElapsedTime_s"] = (
                df["DateTime"] - global_t0
            ).dt.total_seconds()
        if (
            global_t0 is not None
            and not df_steps.empty
            and "StartDateTime" in df_steps.columns
        ):
            df_steps["ElapsedTime_s"] = (
                df_steps["StartDateTime"] - global_t0
            ).dt.total_seconds()

    # --- MODE 1: STACKED (Separate Plots) ---
    if layout_mode == "stacked":
        graphs = []
        for mod in selected_modules:
            if mod not in loaded_data:
                continue
            df, df_steps = loaded_data[mod]
            if df.empty or x_col not in df.columns:
                continue

            mod_display = "Main Chamber" if mod == "." else mod
            fig = build_single_plot(
                df=df,
                df_steps=df_steps,
                x_col=x_col,
                y_cols=y_cols,
                toggle_steps=toggle_steps,
                expanded_steps=expanded_by_mod.get(mod, []),
                pressure_mode=pressure_mode,
                title_suffix="",
            )
            fig.update_layout(title="")

            graphs.append(
                html.Div(
                    className="plot-card",
                    style={
                        "marginBottom": "16px",
                        "backgroundColor": "#FFFFFF",
                        "padding": "14px 16px",
                        "border": "1px solid #E1DFDD",
                        "borderRadius": "2px",
                        "position": "relative",
                    },
                    children=[
                        html.Div(
                            style={
                                "display": "flex",
                                "justifyContent": "space-between",
                                "alignItems": "center",
                                "marginBottom": "6px",
                                "borderBottom": "1px solid #F3F2F1",
                                "paddingBottom": "6px",
                            },
                            children=[
                                html.H3(
                                    mod_display,
                                    style={
                                        "margin": "0",
                                        "fontSize": "13.5px",
                                        "color": "#181B1F",
                                        "fontWeight": "700",
                                        "textTransform": "uppercase",
                                        "letterSpacing": "0.3px",
                                    },
                                ),
                                html.Div(
                                    style={"display": "flex", "alignItems": "center"},
                                    children=[
                                        html.Button(
                                            "Full Screen",
                                            className="btn-fs-toggle",
                                            style={
                                                "fontSize": "11px",
                                                "padding": "4px 10px",
                                                "backgroundColor": "#FAF9F8",
                                                "color": "#323130",
                                                "border": "1px solid #C8C6C4",
                                                "borderRadius": "2px",
                                                "cursor": "pointer",
                                                "fontWeight": "600",
                                            },
                                        ),
                                        help_badge(
                                            "Expand this module chart to full screen (press Esc or click again to exit)."
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        dcc.Graph(
                            figure=fig,
                            style={"height": "52vh"},
                            config={"displaylogo": False, "responsive": True},
                        ),
                    ],
                )
            )
        return (
            graphs
            if graphs
            else html.Div("No data found for selected modules.")
        )

    # --- MODE 2: OVERLAID (Single Plot with Steps & Substeps) ---
    else:
        fig = build_overlaid_plot(
            loaded_data=loaded_data,
            x_col=x_col,
            y_cols=y_cols,
            toggle_steps=toggle_steps,
            expanded_by_mod=expanded_by_mod,
            pressure_mode=pressure_mode,
        )
        display_mods = ["Main Chamber" if m == "." else m for m in selected_modules]

        return html.Div(
            className="plot-card",
            style={
                "backgroundColor": "#FFFFFF",
                "padding": "14px 16px",
                "border": "1px solid #E1DFDD",
                "borderRadius": "2px",
                "position": "relative",
            },
            children=[
                html.Div(
                    style={
                        "display": "flex",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "marginBottom": "6px",
                        "borderBottom": "1px solid #F3F2F1",
                        "paddingBottom": "6px",
                    },
                    children=[
                        html.H3(
                            f"Overlaid Comparison ({', '.join(display_mods)})",
                            style={
                                "margin": "0",
                                "fontSize": "13.5px",
                                "color": "#181B1F",
                                "fontWeight": "700",
                                "textTransform": "uppercase",
                                "letterSpacing": "0.3px",
                            },
                        ),
                        html.Div(
                            style={"display": "flex", "alignItems": "center"},
                            children=[
                                html.Button(
                                    "Full Screen",
                                    className="btn-fs-toggle",
                                    style={
                                        "fontSize": "11px",
                                        "padding": "4px 10px",
                                        "backgroundColor": "#FAF9F8",
                                        "color": "#323130",
                                        "border": "1px solid #C8C6C4",
                                        "borderRadius": "2px",
                                        "cursor": "pointer",
                                        "fontWeight": "600",
                                    },
                                ),
                                help_badge(
                                    "Expand this overlaid comparison chart to full screen (press Esc or click again to exit)."
                                ),
                            ],
                        ),
                    ],
                ),
                dcc.Graph(
                    figure=fig,
                    style={"height": "76vh"},
                    config={"displaylogo": False, "responsive": True},
                ),
            ],
        )


# --- Callback de Geração de Relatórios (Run Report & Wafer History) ---


@app.callback(
    Output("report-status-msg", "children"),
    Output("report-open-url", "children"),
    Input("btn-run-report", "n_clicks"),
    Input("btn-wafer-report", "n_clicks"),
    State("select-run", "value"),
    State("select-wafer", "value"),
    State("select-module", "value"),
    State("layout-mode", "value"),
    State("select-x", "value"),
    State("select-y", "value"),
    State("pressure-mode", "value"),
    State("toggle-steps", "value"),
    State("select-substeps", "value"),
    prevent_initial_call=True,
)
def generate_reports_callback(
    n_run,
    n_wafer,
    selected_run,
    selected_wafer,
    selected_modules,
    layout_mode,
    x_col,
    y_cols,
    pressure_mode,
    toggle_steps,
    expanded_substeps,
):
    ctx = dash.callback_context
    if not ctx.triggered or not selected_run:
        return "", ""

    trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
    if isinstance(selected_modules, str):
        selected_modules = [selected_modules]

    layout_label = "Overlaid" if layout_mode == "overlaid" else "Stacked"

    if trigger_id == "btn-run-report":
        filename = f"Run_Report_{selected_run}.html"
        body_html = generate_run_section_html(
            run_name=selected_run,
            selected_modules=selected_modules,
            layout_mode=layout_mode or "stacked",
            x_col=x_col,
            y_cols=y_cols or [],
            pressure_mode=pressure_mode,
            toggle_steps=toggle_steps,
            expanded_substeps=expanded_substeps or [],
        )
        full_html = wrap_report_document(
            title=f"Process Run Report  |  {selected_run}",
            subtitle="Complete run metadata, interactive parameter trends, channel statistics, and recipe step logs.",
            body_html=body_html,
            filename=filename,
        )
        out_path = REPORTS_DIR / filename
        out_path.write_text(full_html, encoding="utf-8")
        report_url = f"/reports/{filename}?t={int(datetime.now().timestamp())}"

        status_ui = html.Div([
            html.Div(
                "Run Report ready.",
                style={"color": "#107C10", "fontWeight": "600", "marginBottom": "2px"},
            ),
            html.A(
                "Open Report / Print PDF",
                href=report_url,
                target="_blank",
                style={"color": "#0078D4", "fontWeight": "600", "textDecoration": "underline"},
            ),
        ])
        return status_ui, report_url

    elif trigger_id == "btn-wafer-report":
        catalog = get_runs_catalog()
        if catalog.empty:
            return "No runs available.", ""

        target_wafer = selected_wafer
        if not target_wafer:
            run_meta = parse_run_data_sav(LOGS_BASE_DIR / selected_run)
            target_wafer = run_meta.get("Wafer ID", "Unknown")
            if not target_wafer or target_wafer == "Unknown":
                match_row = catalog[catalog["Run"] == selected_run]
                target_wafer = (
                    match_row["Wafer"].iloc[0]
                    if not match_row.empty
                    else selected_run
                )

        wafer_runs_df = catalog[catalog["Wafer"] == target_wafer].sort_values("Run")
        wafer_runs = wafer_runs_df["Run"].tolist()
        if not wafer_runs:
            wafer_runs = [selected_run]

        timeline_rows = []
        for idx, r_name in enumerate(wafer_runs, start=1):
            r_dir = LOGS_BASE_DIR / r_name
            r_meta = parse_run_data_sav(r_dir)
            mods_info = []
            for mod_name in get_active_modules_for_run(r_dir):
                d = r_dir if mod_name == "." else (r_dir / mod_name)
                xml_info = parse_run_sequence_xml(d)
                m_disp = "Main Chamber" if mod_name == "." else mod_name
                mods_info.append(f"{m_disp} ({xml_info.get('RecipeName', 'Unknown')})")

            timeline_rows.append(f"""
                <tr>
                    <td class="mono"><strong>#{idx}</strong></td>
                    <td class="mono"><strong>{html_lib.escape(r_name)}</strong></td>
                    <td class="mono">{html_lib.escape(r_meta.get('Lot ID', 'Unknown'))}</td>
                    <td class="mono">{html_lib.escape(r_meta.get('Sequence Name', 'Unknown'))}</td>
                    <td class="mono">{html_lib.escape(r_meta.get('Start Time', 'Unknown'))} &rarr; {html_lib.escape(r_meta.get('End Time', 'Unknown'))}</td>
                    <td class="mono">{html_lib.escape(r_meta.get('Source Slot', 'Unknown'))}</td>
                    <td class="mono">{html_lib.escape(', '.join(mods_info) if mods_info else 'None')}</td>
                </tr>
            """)

        summary_card = f"""
        <div class="section-card">
            <h2 class="section-title">Wafer Process Timeline  |  Wafer ID: {html_lib.escape(str(target_wafer))} ({len(wafer_runs)} Runs)</h2>
            <table class="report-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Run Log</th>
                        <th>Lot ID</th>
                        <th>Global Sequence</th>
                        <th>Start Date/Time &rarr; End Date/Time</th>
                        <th>Slot</th>
                        <th>Active Modules & Recipes</th>
                    </tr>
                </thead>
                <tbody>
                    {''.join(timeline_rows)}
                </tbody>
            </table>
        </div>
        """

        run_sections = []
        for idx, r_name in enumerate(wafer_runs, start=1):
            sec_html = generate_run_section_html(
                run_name=r_name,
                selected_modules=None,
                layout_mode=layout_mode or "stacked",
                x_col=x_col,
                y_cols=y_cols or [],
                pressure_mode=pressure_mode,
                toggle_steps=toggle_steps,
                expanded_substeps=expanded_substeps or [],
            )
            run_sections.append(f"""
                <div style="margin-top: 22px; border-top: 2px solid #323130; padding-top: 14px;">
                    <h2 style="margin: 0 0 10px 0; color: #181B1F; font-size: 16px; text-transform: uppercase; page-break-after: avoid; break-after: avoid;">
                        Run #{idx} of {len(wafer_runs)}: {html_lib.escape(r_name)}
                    </h2>
                    {sec_html}
                </div>
            """)

        safe_wafer = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(target_wafer))
        filename = f"Wafer_History_{safe_wafer}.html"
        full_html = wrap_report_document(
            title=f"Wafer History Report  |  Wafer ID: {target_wafer}",
            subtitle=f"Complete chronological tracking across {len(wafer_runs)} process run(s).",
            body_html=summary_card + "\n".join(run_sections),
            filename=filename,
        )
        out_path = REPORTS_DIR / filename
        out_path.write_text(full_html, encoding="utf-8")
        report_url = f"/reports/{filename}?t={int(datetime.now().timestamp())}"

        status_ui = html.Div([
            html.Div(
                f"Wafer History ({len(wafer_runs)} runs) ready.",
                style={"color": "#107C10", "fontWeight": "600", "marginBottom": "2px"},
            ),
            html.A(
                "Open Report / Print PDF",
                href=report_url,
                target="_blank",
                style={"color": "#0078D4", "fontWeight": "600", "textDecoration": "underline"},
            ),
        ])
        return status_ui, report_url

    return "", ""


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=8050)