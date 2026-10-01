from __future__ import annotations

import io
import uuid
from typing import Any

import httpx
import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    API_URL: str = str(st.secrets["API_URL"])
except Exception:
    API_URL = "http://localhost:8000"

REQUEST_TIMEOUT = 60.0

EXAMPLE_QUESTIONS = [
    "Top 5 produits par chiffre d'affaires",
    "CA mensuel des commandes livrées",
    "Clients ayant dépensé plus de 500 €",
    "Taux de remise moyen par catégorie",
    "Répartition des commandes par statut",
    "Produits jamais commandés",
]

_ERROR_LABELS: dict[str, str] = {
    "validation_rejected": "Question bloquée par les règles de sécurité.",
    "repair_exhausted": "Impossible de générer une requête valide après plusieurs tentatives.",
    "query_timeout": "La requête a dépassé le délai maximum autorisé.",
    "llm_unavailable": "Le service LLM est temporairement indisponible.",
    "agent_error": "Erreur interne de l'agent.",
}

# ---------------------------------------------------------------------------
# Design system — Retool / Linear tokens
# ---------------------------------------------------------------------------
# Sidebar  : #18181b  zinc-950  (Retool dark sidebar)
# App bg   : #fafafa  zinc-50
# Surface  : #ffffff
# Muted bg : #f4f4f5  zinc-100
# Border   : #e4e4e7  zinc-200
# Text-1   : #18181b  zinc-900
# Text-2   : #3f3f46  zinc-700
# Text-3   : #71717a  zinc-500
# Accent   : #5e6ad2  Linear lavender
# ---------------------------------------------------------------------------

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Base ── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased !important;
}

/* ── Shell ── */
.stApp { background-color: #fafafa !important; }
#MainMenu, footer { visibility: hidden; }
header { visibility: hidden; }
[data-testid="collapsedControl"] { visibility: visible !important; display: flex !important; }
[data-testid="stToolbar"] { display: none !important; }
.stDeployButton { display: none !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background-color: #18181b !important;
    border-right: none !important;
    box-shadow: 1px 0 0 rgba(255,255,255,0.06);
}
[data-testid="stSidebarContent"] { padding: 0 0.85rem; }

[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.07) !important;
    margin: 0.6rem 0 !important;
}

/* Sidebar — "New conversation" primary button */
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] button,
[data-testid="stSidebar"] .stButton:has(button[kind="primary"]) button {
    background: #5e6ad2 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    padding: 0.45rem 0.8rem !important;
    transition: background 0.12s !important;
    font-family: 'Inter', sans-serif !important;
    letter-spacing: -0.01em !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] button:hover {
    background: #4a54c0 !important;
}

/* Sidebar — example question buttons */
[data-testid="stSidebar"] .stButton button {
    background: transparent !important;
    color: #94a3b8 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 6px !important;
    font-size: 0.75rem !important;
    text-align: left !important;
    padding: 0.38rem 0.65rem !important;
    line-height: 1.45 !important;
    transition: background 0.1s, color 0.1s !important;
    font-family: 'Inter', sans-serif !important;
    white-space: normal !important;
    height: auto !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.05) !important;
    color: #d4d4d8 !important;
    border-color: rgba(255,255,255,0.15) !important;
}

/* ── Main container ── */
.main .block-container {
    padding: 2.25rem 2.75rem 6rem !important;
    max-width: 840px !important;
}

/* ── Chat messages ── */
[data-testid="stChatMessage"] {
    background: transparent !important;
    border: none !important;
    padding: 0.15rem 0 !important;
    gap: 0.75rem !important;
}

/* User bubble */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    flex-direction: row-reverse !important;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) .stMarkdown p {
    background: #18181b !important;
    color: #fafafa !important;
    border-radius: 16px 16px 4px 16px !important;
    padding: 0.65rem 1rem !important;
    display: inline-block !important;
    font-size: 0.9rem !important;
    line-height: 1.55 !important;
    max-width: 85% !important;
}

/* Assistant card */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) {
    background: #ffffff !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 12px !important;
    padding: 1.1rem 1.25rem 0.85rem !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04) !important;
    margin: 0.3rem 0 0.65rem !important;
}

/* Avatar icons */
[data-testid="stChatMessageAvatarUser"] {
    background: #18181b !important;
    color: #ffffff !important;
    border-radius: 8px !important;
    border: none !important;
    width: 32px !important;
    height: 32px !important;
    font-size: 0.75rem !important;
    font-weight: 600 !important;
    flex-shrink: 0 !important;
}
[data-testid="stChatMessageAvatarAssistant"] {
    background: #5e6ad2 !important;
    color: #ffffff !important;
    border-radius: 8px !important;
    border: none !important;
    width: 32px !important;
    height: 32px !important;
    font-size: 0.75rem !important;
    flex-shrink: 0 !important;
}

/* ── Chat input ── */
[data-testid="stChatInputContainer"] {
    background: #ffffff !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 10px !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
    transition: border-color 0.15s, box-shadow 0.15s !important;
}
[data-testid="stChatInputContainer"]:focus-within {
    border-color: #5e6ad2 !important;
    box-shadow: 0 0 0 3px rgba(94,106,210,0.12), 0 1px 3px rgba(0,0,0,0.06) !important;
}
[data-testid="stChatInput"] textarea {
    background: transparent !important;
    color: #f4f4f5 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    caret-color: #5e6ad2 !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #71717a !important; }

/* ── SQL expander ── */
[data-testid="stExpander"] {
    background: #f4f4f5 !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    margin-bottom: 0.8rem !important;
}
[data-testid="stExpander"] summary {
    color: #71717a !important;
    font-size: 0.7rem !important;
    letter-spacing: 0.08em !important;
    text-transform: uppercase !important;
    font-weight: 600 !important;
    padding: 0.55rem 0.9rem !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stExpander"] summary:hover { color: #3f3f46 !important; }
[data-testid="stExpander"] summary svg { color: #a1a1aa !important; }

/* ── SQL code block ── */
.stCode, [data-testid="stCode"] {
    background: #18181b !important;
    border-radius: 6px !important;
    border: none !important;
}
.stCode code, pre code {
    font-family: 'JetBrains Mono', 'Fira Code', monospace !important;
    font-size: 0.78rem !important;
    line-height: 1.7 !important;
    color: #a5b4fc !important;
}

/* SQL keywords highlight via color */
.stCode .k, .stCode .kd { color: #c084fc !important; }
.stCode .s, .stCode .s1, .stCode .s2 { color: #86efac !important; }
.stCode .c, .stCode .c1 { color: #6b7280 !important; }
.stCode .n { color: #7dd3fc !important; }

/* ── Dataframe ── */
[data-testid="stDataFrame"] {
    border: 1px solid #e4e4e7 !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
}

/* ── Info/Error alerts ── */
.stAlert {
    border-radius: 8px !important;
    font-size: 0.84rem !important;
    font-family: 'Inter', sans-serif !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] button {
    background: #ffffff !important;
    color: #71717a !important;
    border: 1px solid #e4e4e7 !important;
    border-radius: 6px !important;
    font-size: 0.71rem !important;
    font-weight: 500 !important;
    padding: 0.22rem 0.6rem !important;
    font-family: 'Inter', sans-serif !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
    transition: all 0.1s !important;
}
[data-testid="stDownloadButton"] button:hover {
    background: #f4f4f5 !important;
    color: #18181b !important;
    border-color: #d4d4d8 !important;
}

/* ── Markdown in main area ── */
.stMarkdown p { color: #3f3f46 !important; line-height: 1.6 !important; }
.stMarkdown strong { color: #18181b !important; }

/* ── Spinner ── */
[data-testid="stSpinner"] { color: #5e6ad2 !important; }

/* ── Dividers ── */
hr { border-color: #e4e4e7 !important; margin: 0.75rem 0 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d4d4d8; border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: #a1a1aa; }
</style>
"""

# ---------------------------------------------------------------------------
# Plotly — matches light surface, accent lavender
# ---------------------------------------------------------------------------

_PLOTLY_LAYOUT: dict[str, Any] = {
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#ffffff",
    "font": {"family": "Inter, sans-serif", "size": 11, "color": "#71717a"},
    "height": 300,
    "margin": {"t": 32, "b": 8, "l": 4, "r": 4},
    "showlegend": False,
    "xaxis": {
        "gridcolor": "#f4f4f5",
        "linecolor": "#e4e4e7",
        "tickfont": {"color": "#a1a1aa", "size": 10},
        "title_font": {"color": "#a1a1aa"},
        "zeroline": False,
    },
    "yaxis": {
        "gridcolor": "#f4f4f5",
        "linecolor": "#e4e4e7",
        "tickfont": {"color": "#a1a1aa", "size": 10},
        "title_font": {"color": "#a1a1aa"},
        "zeroline": False,
    },
    "title_font": {"size": 12, "color": "#71717a", "family": "Inter, sans-serif"},
    "hoverlabel": {
        "bgcolor": "#18181b",
        "bordercolor": "#3f3f46",
        "font": {"family": "Inter", "size": 11, "color": "#fafafa"},
    },
}

_COLOR_SEQ = ["#5e6ad2", "#7c3aed", "#0891b2", "#059669", "#d97706", "#e11d48"]

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _post_query(question: str, session_id: str) -> dict[str, Any]:
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        r = client.post(
            f"{API_URL}/v1/query",
            json={"question": question, "session_id": session_id},
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]


def _delete_session(session_id: str) -> None:
    try:
        with httpx.Client(timeout=5.0) as client:
            client.delete(f"{API_URL}/v1/sessions/{session_id}")
    except Exception:
        pass


@st.cache_data(ttl=20, show_spinner=False)
def _api_healthy() -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            return client.get(f"{API_URL}/healthz").status_code == 200
    except Exception:
        return False



# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _init_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state["messages"] = []


def _new_conversation() -> None:
    _delete_session(st.session_state["session_id"])
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["messages"] = []


# ---------------------------------------------------------------------------
# Auto-viz
# ---------------------------------------------------------------------------


def _auto_chart(df: pd.DataFrame) -> None:
    if df.empty or len(df.columns) < 2:
        return

    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cat_cols = [
        c for c in df.columns if df[c].dtype == object and df[c].nunique() <= 30
    ]

    fig = None

    if date_cols and num_cols:
        fig = px.line(
            df,
            x=date_cols[0],
            y=num_cols[0],
            title=num_cols[0],
            color_discrete_sequence=_COLOR_SEQ,
        )
        fig.update_traces(line_width=2, line_shape="spline")
        fig.update_layout(xaxis_tickangle=-30)

    elif cat_cols and num_cols:
        top = (
            df[[cat_cols[0], num_cols[0]]]
            .sort_values(num_cols[0], ascending=False)
            .head(15)
        )
        fig = px.bar(
            top,
            x=num_cols[0],
            y=cat_cols[0],
            orientation="h",
            title=num_cols[0],
            color=num_cols[0],
            color_continuous_scale=[[0, "#e0e7ff"], [1, "#5e6ad2"]],
        )
        fig.update_layout(
            coloraxis_showscale=False, yaxis={"categoryorder": "total ascending"}
        )
        fig.update_traces(marker_line_width=0)

    elif len(num_cols) >= 2:
        fig = px.scatter(
            df,
            x=num_cols[0],
            y=num_cols[1],
            title=f"{num_cols[1]} / {num_cols[0]}",
            color_discrete_sequence=_COLOR_SEQ,
        )
        fig.update_traces(marker_size=8, opacity=0.7)

    if fig is not None:
        fig.update_layout(**_PLOTLY_LAYOUT)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _to_dataframe(msg: dict[str, Any]) -> pd.DataFrame | None:
    cols = msg.get("columns")
    rows = msg.get("rows")
    if not cols or not rows:
        return None
    try:
        df = pd.DataFrame(rows, columns=cols)
        for col in df.columns:
            if df[col].dtype == object:
                try:
                    df[col] = pd.to_datetime(df[col])
                except (ValueError, TypeError):
                    pass
        return df
    except Exception:
        return None


def _meta_strip(msg: dict[str, Any], df: pd.DataFrame | None) -> None:
    rc = msg.get("row_count", 0)
    att = msg.get("attempts", 1)
    lat = msg.get("latency_ms", 0.0)
    trunc = (
        "&ensp;·&ensp;<span style='color:#f59e0b;'>tronqué</span>"
        if msg.get("truncated")
        else ""
    )

    col_l, col_r = st.columns([5, 1])
    col_l.markdown(
        f"<p style='font-size:0.71rem;color:#a1a1aa;margin:0.5rem 0 0;"
        f"font-family:Inter,sans-serif;'>"
        f"{rc} ligne{'s' if rc != 1 else ''}{trunc}"
        f"&ensp;·&ensp;{att} tentative{'s' if att != 1 else ''}"
        f"&ensp;·&ensp;{lat:.0f}&thinsp;ms</p>",
        unsafe_allow_html=True,
    )
    if df is not None and not df.empty:
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        col_r.download_button(
            label="CSV ↓",
            data=buf.getvalue(),
            file_name="resultats.csv",
            mime="text/csv",
            key=f"dl_{msg['_idx']}",
        )


def _render_success(msg: dict[str, Any]) -> None:
    with st.expander("SQL · voir la requête", expanded=False):
        st.code(msg["sql"], language="sql")

    df = _to_dataframe(msg)
    if df is not None and not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
        _auto_chart(df)
    else:
        st.markdown(
            "<p style='color:#a1a1aa;font-size:0.84rem;margin:0.4rem 0;'>"
            "Aucun résultat pour cette requête.</p>",
            unsafe_allow_html=True,
        )
    _meta_strip(msg, df)


def _render_error(msg: dict[str, Any]) -> None:
    code = msg.get("error_code", "agent_error")
    text = msg.get("reason") or _ERROR_LABELS.get(code, "Erreur inattendue.")
    if code == "unanswerable":
        st.info(f"ℹ️  {text}")
    else:
        st.error(f"❌  {text}")


def _replay_messages() -> None:
    for msg in st.session_state["messages"]:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            elif msg["content_type"] == "success":
                _render_success(msg)
            else:
                _render_error(msg)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _render_sidebar() -> None:
    with st.sidebar:
        # Brand
        st.markdown(
            "<div style='padding:1rem 0 0.25rem;'>"
            "<p style='color:#f4f4f5;font-size:0.95rem;font-weight:600;"
            "letter-spacing:-0.015em;margin:0;line-height:1.2;'>Boutique Analytics</p>"
            "<p style='color:#71717a;font-size:0.7rem;margin:0.2rem 0 0;"
            "letter-spacing:0.02em;'>SQL AI Agent</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # Status
        healthy = _api_healthy()
        dot_color = "#22c55e" if healthy else "#ef4444"
        label = "API connectée" if healthy else "API indisponible"
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:6px;margin:0.1rem 0;'>"
            f"<span style='width:6px;height:6px;border-radius:50%;"
            f"background:{dot_color};flex-shrink:0;display:inline-block;'></span>"
            f"<span style='font-size:0.72rem;color:#94a3b8;'>{label}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # Session
        st.markdown(
            "<p style='font-size:0.65rem;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:0.1em;font-weight:600;margin:0 0 0.45rem;'>Session</p>",
            unsafe_allow_html=True,
        )
        sid = st.session_state["session_id"]
        st.markdown(
            f"<p style='font-size:0.68rem;color:#9ca3af;font-family:"
            f"JetBrains Mono,monospace;margin:0 0 0.5rem;"
            f"word-break:break-all;'>{sid[:20]}…</p>",
            unsafe_allow_html=True,
        )
        if st.button(
            "⟳  Nouvelle conversation",
            use_container_width=True,
            type="primary",
            key="new_conv",
        ):
            _new_conversation()
            st.rerun()

        st.divider()

        # Examples
        st.markdown(
            "<p style='font-size:0.65rem;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:0.1em;font-weight:600;margin:0 0 0.5rem;'>Exemples</p>",
            unsafe_allow_html=True,
        )
        for q in EXAMPLE_QUESTIONS:
            if st.button(q, use_container_width=True, key=f"ex_{hash(q)}"):
                st.session_state["_prefill"] = q
                st.rerun()


# ---------------------------------------------------------------------------
# Welcome
# ---------------------------------------------------------------------------


def _render_welcome() -> None:
    st.markdown(
        """
        <div style="
            display:flex;flex-direction:column;align-items:center;
            padding:5rem 1rem 2rem;text-align:center;
        ">
            <div style="
                width:48px;height:48px;border-radius:12px;
                background:linear-gradient(135deg,#5e6ad2 0%,#8b5cf6 100%);
                display:flex;align-items:center;justify-content:center;
                font-size:1.35rem;margin-bottom:1.25rem;
                box-shadow:0 4px 16px rgba(94,106,210,0.3);
            ">🏪</div>
            <h1 style="
                color:#18181b;font-size:1.45rem;font-weight:700;
                letter-spacing:-0.03em;margin:0 0 0.5rem;
                font-family:Inter,sans-serif;
            ">Boutique Analytics</h1>
            <p style="
                color:#71717a;font-size:0.88rem;line-height:1.65;
                max-width:380px;margin:0 0 2rem;font-family:Inter,sans-serif;
            ">
                Posez une question en français.<br>
                L'agent génère le SQL, l'exécute, et vous affiche le résultat.
            </p>
            <div style="display:flex;flex-wrap:wrap;gap:0.4rem;justify-content:center;max-width:480px;">
                <span style="font-size:0.72rem;color:#71717a;background:#ffffff;
                    border:1px solid #e4e4e7;border-radius:99px;padding:0.28rem 0.75rem;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);font-family:Inter,sans-serif;">Commandes</span>
                <span style="font-size:0.72rem;color:#71717a;background:#ffffff;
                    border:1px solid #e4e4e7;border-radius:99px;padding:0.28rem 0.75rem;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);font-family:Inter,sans-serif;">Produits</span>
                <span style="font-size:0.72rem;color:#71717a;background:#ffffff;
                    border:1px solid #e4e4e7;border-radius:99px;padding:0.28rem 0.75rem;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);font-family:Inter,sans-serif;">Clients</span>
                <span style="font-size:0.72rem;color:#71717a;background:#ffffff;
                    border:1px solid #e4e4e7;border-radius:99px;padding:0.28rem 0.75rem;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);font-family:Inter,sans-serif;">CA &amp; Remises</span>
                <span style="font-size:0.72rem;color:#71717a;background:#ffffff;
                    border:1px solid #e4e4e7;border-radius:99px;padding:0.28rem 0.75rem;
                    box-shadow:0 1px 2px rgba(0,0,0,0.05);font-family:Inter,sans-serif;">Statistiques</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Input handler
# ---------------------------------------------------------------------------


def _handle_input() -> None:
    prefill: str | None = st.session_state.get("_prefill")
    if "_prefill" in st.session_state:
        del st.session_state["_prefill"]

    question: str | None = st.chat_input("Posez votre question…") or prefill
    if not question:
        return

    idx = len(st.session_state["messages"])

    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Génération du SQL…"):
            try:
                data = _post_query(question, st.session_state["session_id"])
            except httpx.HTTPStatusError as exc:
                body: dict[str, Any] = {}
                try:
                    body = exc.response.json()
                except Exception:
                    pass
                err: dict[str, Any] = {
                    "role": "assistant",
                    "content_type": "error",
                    "error_code": body.get("error", "agent_error"),
                    "_idx": idx + 1,
                }
                st.session_state["messages"].append(err)
                _render_error(err)
                return
            except httpx.TimeoutException:
                err = {
                    "role": "assistant",
                    "content_type": "error",
                    "error_code": "query_timeout",
                    "_idx": idx + 1,
                }
                st.session_state["messages"].append(err)
                _render_error(err)
                return
            except Exception:
                err = {
                    "role": "assistant",
                    "content_type": "error",
                    "error_code": "agent_error",
                    "_idx": idx + 1,
                }
                st.session_state["messages"].append(err)
                _render_error(err)
                return

        if data.get("unanswerable"):
            un: dict[str, Any] = {
                "role": "assistant",
                "content_type": "error",
                "error_code": "unanswerable",
                "reason": data.get("reason", ""),
                "_idx": idx + 1,
            }
            st.session_state["messages"].append(un)
            _render_error(un)
            return

        ok: dict[str, Any] = {
            "role": "assistant",
            "content_type": "success",
            "sql": data.get("sql", ""),
            "columns": data.get("columns", []),
            "rows": data.get("rows", []),
            "row_count": data.get("row_count", 0),
            "truncated": data.get("truncated", False),
            "attempts": data.get("attempts", 1),
            "latency_ms": data.get("latency_ms", 0.0),
            "_idx": idx + 1,
        }
        st.session_state["messages"].append(ok)
        _render_success(ok)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Boutique Analytics",
        page_icon="🏪",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    _init_state()
    _render_sidebar()

    if not st.session_state["messages"]:
        _render_welcome()

    _replay_messages()
    _handle_input()


main()
