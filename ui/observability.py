from __future__ import annotations

import time
from typing import Any

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

try:
    API_URL: str = str(st.secrets["API_URL"])
except Exception:
    API_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Design tokens — same system as app.py
# ---------------------------------------------------------------------------

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased !important;
}

.stApp { background-color: #fafafa !important; }
#MainMenu, footer { visibility: hidden; }
header { visibility: hidden; }
[data-testid="collapsedControl"] { visibility: visible !important; display: flex !important; }
[data-testid="stToolbar"] { display: none !important; }
.stDeployButton { display: none !important; }

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

[data-testid="stSidebar"] .stButton button {
    background: transparent !important;
    color: #94a3b8 !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 6px !important;
    font-size: 0.75rem !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stSidebar"] .stButton button:hover {
    background: rgba(255,255,255,0.05) !important;
    color: #d4d4d8 !important;
}

[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] button {
    background: #ef4444 !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 6px !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] button:hover {
    background: #dc2626 !important;
}

.main .block-container {
    padding: 2rem 2.5rem 4rem !important;
    max-width: 1200px !important;
}

hr { border-color: #e4e4e7 !important; margin: 0.75rem 0 !important; }

::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d4d4d8; border-radius: 99px; }
</style>
"""

_COLOR_SEQ = ["#5e6ad2", "#7c3aed", "#0891b2", "#059669", "#d97706", "#e11d48"]

_PLOTLY_BASE: dict[str, Any] = {
    "paper_bgcolor": "#ffffff",
    "plot_bgcolor": "#ffffff",
    "font": {"family": "Inter, sans-serif", "size": 11, "color": "#71717a"},
    "margin": {"t": 36, "b": 8, "l": 4, "r": 4},
    "showlegend": False,
    "xaxis": {
        "gridcolor": "#f4f4f5",
        "linecolor": "#e4e4e7",
        "tickfont": {"color": "#a1a1aa", "size": 10},
        "zeroline": False,
    },
    "yaxis": {
        "gridcolor": "#f4f4f5",
        "linecolor": "#e4e4e7",
        "tickfont": {"color": "#a1a1aa", "size": 10},
        "zeroline": False,
    },
    "title_font": {"size": 12, "color": "#71717a", "family": "Inter, sans-serif"},
    "hoverlabel": {
        "bgcolor": "#18181b",
        "bordercolor": "#3f3f46",
        "font": {"family": "Inter", "size": 11, "color": "#fafafa"},
    },
}

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@st.cache_data(ttl=5, show_spinner=False)
def _fetch_metrics() -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{API_URL}/v1/metrics")
            if r.status_code == 200:
                return r.json()  # type: ignore[no-any-return]
    except Exception:
        pass
    return None


def _reset_metrics() -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.delete(f"{API_URL}/v1/metrics/reset")
            return r.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# KPI card helper
# ---------------------------------------------------------------------------

_KPI_CARD = """
<div style="
    background:#ffffff;
    border:1px solid #e4e4e7;
    border-radius:10px;
    padding:1rem 1.1rem 0.85rem;
    box-shadow:0 1px 3px rgba(0,0,0,0.05);
    min-height:82px;
">
    <p style="font-size:0.68rem;color:#a1a1aa;text-transform:uppercase;
              letter-spacing:0.08em;font-weight:600;margin:0 0 0.35rem;
              font-family:Inter,sans-serif;">{label}</p>
    <p style="font-size:1.55rem;font-weight:700;color:{color};
              margin:0;line-height:1.15;font-family:Inter,sans-serif;
              letter-spacing:-0.03em;">{value}</p>
    {sub}
</div>
"""

_KPI_SUB = (
    "<p style='font-size:0.7rem;color:#a1a1aa;margin:0.25rem 0 0;"
    "font-family:Inter,sans-serif;'>{}</p>"
)


def _kpi(label: str, value: str, color: str = "#18181b", sub: str = "") -> str:
    return _KPI_CARD.format(
        label=label,
        value=value,
        color=color,
        sub=_KPI_SUB.format(sub) if sub else "",
    )


def _section(title: str) -> None:
    st.markdown(
        f"<h3 style='font-size:0.8rem;font-weight:600;color:#71717a;"
        f"text-transform:uppercase;letter-spacing:0.09em;margin:1.6rem 0 0.7rem;"
        f"font-family:Inter,sans-serif;border-bottom:1px solid #e4e4e7;"
        f"padding-bottom:0.45rem;'>{title}</h3>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Dashboard sections
# ---------------------------------------------------------------------------


def _render_requests(m: dict[str, Any]) -> None:
    _section("Requêtes")
    req = m.get("requests", {})
    total = req.get("total", 0)
    c1, c2, c3, c4, c5 = st.columns(5)

    sr = req.get("success_rate_pct", 0.0)
    sr_color = "#16a34a" if sr >= 90 else "#d97706" if sr >= 70 else "#dc2626"
    er = req.get("error_rate_pct", 0.0)
    er_color = "#dc2626" if er > 10 else "#d97706" if er > 5 else "#16a34a"

    c1.markdown(_kpi("Total requêtes", str(total)), unsafe_allow_html=True)
    c2.markdown(
        _kpi(
            "Taux de succès",
            f"{sr:.1f}%",
            sr_color,
            f"{req.get('successful', 0)} réussies",
        ),
        unsafe_allow_html=True,
    )
    c3.markdown(
        _kpi(
            "Taux d'erreur", f"{er:.1f}%", er_color, f"{req.get('failed', 0)} échouées"
        ),
        unsafe_allow_html=True,
    )
    c4.markdown(
        _kpi(
            "Non-répondables",
            f"{req.get('unanswerable_rate_pct', 0.0):.1f}%",
            "#71717a",
            f"{req.get('unanswerable', 0)} requêtes",
        ),
        unsafe_allow_html=True,
    )
    c5.markdown(
        _kpi(
            "Bloquées guardrails",
            str(req.get("guardrails_blocked", 0)),
            "#7c3aed",
        ),
        unsafe_allow_html=True,
    )


def _render_latency(m: dict[str, Any]) -> None:
    _section("Latence")
    lat = m.get("latency", {})
    llm = m.get("llm", {})
    exc = m.get("execution", {})
    val = m.get("validation", {})

    c1, c2, c3, c4 = st.columns(4)
    p50 = lat.get("p50_ms", 0.0)
    p95 = lat.get("p95_ms", 0.0)
    p99 = lat.get("p99_ms", 0.0)
    avg = lat.get("avg_ms", 0.0)

    p50_color = "#16a34a" if p50 < 2000 else "#d97706" if p50 < 5000 else "#dc2626"
    p95_color = "#16a34a" if p95 < 5000 else "#d97706" if p95 < 10000 else "#dc2626"

    c1.markdown(
        _kpi("p50 total", f"{p50:.0f} ms", p50_color, f"avg {avg:.0f} ms"),
        unsafe_allow_html=True,
    )
    c2.markdown(_kpi("p95 total", f"{p95:.0f} ms", p95_color), unsafe_allow_html=True)
    c3.markdown(_kpi("p99 total", f"{p99:.0f} ms", "#71717a"), unsafe_allow_html=True)

    # Breakdown bar chart
    breakdown_data = {
        "Composant": ["LLM (p50)", "LLM (p95)", "Exécution (p50)", "Validation (p50)"],
        "ms": [
            llm.get("response_p50_ms", 0.0),
            llm.get("response_p95_ms", 0.0),
            exc.get("p50_ms", 0.0),
            val.get("p50_ms", 0.0),
        ],
    }
    df_lat = pd.DataFrame(breakdown_data)
    fig = px.bar(
        df_lat,
        x="ms",
        y="Composant",
        orientation="h",
        title="Latence par composant (ms)",
        color="ms",
        color_continuous_scale=[[0, "#e0e7ff"], [1, "#5e6ad2"]],
    )
    fig.update_layout(**{**_PLOTLY_BASE, "height": 200, "coloraxis_showscale": False})
    fig.update_traces(marker_line_width=0)
    fig.update_layout(
        yaxis={"categoryorder": "total ascending", **_PLOTLY_BASE["yaxis"]}
    )
    c4.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_throughput(m: dict[str, Any]) -> None:
    rpm_series = m.get("throughput_per_minute", [])
    if not rpm_series:
        return
    _section("Volume de requêtes (req/min)")
    df_rpm = pd.DataFrame(rpm_series)
    if df_rpm.empty or "minute" not in df_rpm.columns:
        st.markdown(
            "<p style='color:#a1a1aa;font-size:0.82rem;'>Pas encore de données.</p>",
            unsafe_allow_html=True,
        )
        return

    df_rpm["time"] = pd.to_datetime(df_rpm["minute"] * 60, unit="s")
    fig = px.area(
        df_rpm,
        x="time",
        y="count",
        title="Requêtes par minute",
        color_discrete_sequence=["#5e6ad2"],
    )
    fig.update_traces(
        line_width=2, line_shape="spline", fillcolor="rgba(94,106,210,0.12)"
    )
    fig.update_layout(**{**_PLOTLY_BASE, "height": 220})
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_tokens(m: dict[str, Any]) -> None:
    _section("Tokens & Coût")
    tok = m.get("tokens", {})
    cost = m.get("cost", {})

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        _kpi(
            "Tokens prompt",
            f"{tok.get('prompt', 0):,}",
            "#18181b",
            f"avg {tok.get('avg_per_request', 0):,}/req",
        ),
        unsafe_allow_html=True,
    )
    c2.markdown(
        _kpi("Tokens completion", f"{tok.get('completion', 0):,}"),
        unsafe_allow_html=True,
    )
    c3.markdown(
        _kpi("Coût total", f"${cost.get('total_usd', 0.0):.4f}", "#5e6ad2"),
        unsafe_allow_html=True,
    )
    c4.markdown(
        _kpi("Coût moyen/req", f"${cost.get('avg_per_request_usd', 0.0):.5f}"),
        unsafe_allow_html=True,
    )

    # Token donut
    prompt = tok.get("prompt", 0)
    completion = tok.get("completion", 0)
    if prompt + completion > 0:
        fig = go.Figure(
            go.Pie(
                labels=["Prompt", "Completion"],
                values=[prompt, completion],
                hole=0.6,
                marker_colors=["#5e6ad2", "#a5b4fc"],
                textfont_size=11,
            )
        )
        fig.update_layout(
            **{
                **_PLOTLY_BASE,
                "height": 200,
                "showlegend": True,
                "legend": {"font": {"size": 10, "color": "#71717a"}},
            },
            title="Répartition tokens",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_validation(m: dict[str, Any]) -> None:
    _section("Validation & Erreurs")
    val = m.get("validation", {})
    err = m.get("errors_by_type", {})
    by_rule = val.get("by_rule", {})

    c1, c2 = st.columns(2)

    # Validation failures by rule
    with c1:
        vf = val.get("failures", 0)
        vfr = val.get("failure_rate_pct", 0.0)
        vf_color = "#dc2626" if vfr > 10 else "#d97706" if vfr > 5 else "#16a34a"
        st.markdown(
            _kpi("Échecs validation", str(vf), vf_color, f"{vfr:.1f}% des requêtes"),
            unsafe_allow_html=True,
        )
        if by_rule:
            df_rules = pd.DataFrame(
                [
                    {"Règle": k, "Occurrences": v}
                    for k, v in sorted(by_rule.items(), key=lambda x: -x[1])
                ]
            )
            fig = px.bar(
                df_rules,
                x="Occurrences",
                y="Règle",
                orientation="h",
                title="Échecs par règle",
                color="Occurrences",
                color_continuous_scale=[[0, "#fee2e2"], [1, "#dc2626"]],
            )
            fig.update_layout(
                **{**_PLOTLY_BASE, "height": 200, "coloraxis_showscale": False}
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending", **_PLOTLY_BASE["yaxis"]}
            )
            fig.update_traces(marker_line_width=0)
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )
        else:
            st.markdown(
                "<p style='color:#a1a1aa;font-size:0.82rem;margin-top:0.5rem;'>Aucun échec de validation.</p>",
                unsafe_allow_html=True,
            )

    with c2:
        if err:
            df_err = pd.DataFrame(
                [
                    {"Type": k, "Occurrences": v}
                    for k, v in sorted(err.items(), key=lambda x: -x[1])
                ]
            )
            fig = px.bar(
                df_err,
                x="Occurrences",
                y="Type",
                orientation="h",
                title="Erreurs par type",
                color="Occurrences",
                color_continuous_scale=[[0, "#fef3c7"], [1, "#d97706"]],
            )
            fig.update_layout(
                **{**_PLOTLY_BASE, "height": 240, "coloraxis_showscale": False}
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending", **_PLOTLY_BASE["yaxis"]}
            )
            fig.update_traces(marker_line_width=0)
            st.plotly_chart(
                fig, use_container_width=True, config={"displayModeBar": False}
            )
        else:
            st.markdown(
                "<p style='color:#a1a1aa;font-size:0.82rem;'>Aucune erreur enregistrée.</p>",
                unsafe_allow_html=True,
            )


def _render_repair(m: dict[str, Any]) -> None:
    _section("Boucle de réparation")
    rep = m.get("repair", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    attempts = rep.get("attempts", 0)
    exhausted = rep.get("exhausted", 0)
    recovered = rep.get("recovered", 0)
    rec_rate = rep.get("recovery_rate_pct", 0.0)
    multi_rate = rep.get("multi_attempt_rate_pct", 0.0)

    rec_color = (
        "#16a34a" if rec_rate >= 80 else "#d97706" if rec_rate >= 50 else "#dc2626"
    )
    exh_color = "#dc2626" if exhausted > 0 else "#16a34a"

    c1.markdown(
        _kpi("Tentatives réparation", str(attempts), "#7c3aed"), unsafe_allow_html=True
    )
    c2.markdown(_kpi("Récupérées", str(recovered), "#16a34a"), unsafe_allow_html=True)
    c3.markdown(_kpi("Épuisées", str(exhausted), exh_color), unsafe_allow_html=True)
    c4.markdown(
        _kpi("Taux de récupération", f"{rec_rate:.1f}%", rec_color),
        unsafe_allow_html=True,
    )
    c5.markdown(
        _kpi(
            "Tentatives multiples",
            f"{multi_rate:.1f}%",
            "#71717a",
            f"avg {rep.get('avg_attempts_per_request', 1.0):.2f} tentatives/req",
        ),
        unsafe_allow_html=True,
    )


def _render_model(m: dict[str, Any]) -> None:
    model_dist = m.get("model_distribution", {})
    if not model_dist:
        return
    _section("Distribution des modèles")
    df_mdl = pd.DataFrame(
        [
            {"Modèle": k, "Appels": v}
            for k, v in sorted(model_dist.items(), key=lambda x: -x[1])
        ]
    )
    c1, c2 = st.columns([1, 2])
    with c1:
        fig = go.Figure(
            go.Pie(
                labels=df_mdl["Modèle"],
                values=df_mdl["Appels"],
                hole=0.55,
                marker_colors=_COLOR_SEQ,
                textfont_size=10,
            )
        )
        fig.update_layout(
            **{
                **_PLOTLY_BASE,
                "height": 220,
                "showlegend": True,
                "legend": {"font": {"size": 10, "color": "#71717a"}},
            },
            title="Répartition modèles",
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.dataframe(df_mdl, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _render_sidebar(m: dict[str, Any] | None) -> None:
    with st.sidebar:
        st.markdown(
            "<div style='padding:1rem 0 0.25rem;'>"
            "<p style='color:#f4f4f5;font-size:0.95rem;font-weight:600;"
            "letter-spacing:-0.015em;margin:0;line-height:1.2;'>Observabilité</p>"
            "<p style='color:#71717a;font-size:0.7rem;margin:0.2rem 0 0;"
            "letter-spacing:0.02em;'>SQL AI Agent · Métriques</p>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        # Uptime
        if m:
            uptime_s = m.get("uptime_seconds", 0)
            h, rem = divmod(uptime_s, 3600)
            mn, s = divmod(rem, 60)
            uptime_str = f"{h}h {mn}m {s}s" if h else f"{mn}m {s}s"
            st.markdown(
                f"<p style='font-size:0.72rem;color:#94a3b8;margin:0.2rem 0 0.1rem;'>"
                f"⏱ Uptime&ensp;<strong style='color:#d4d4d8;'>{uptime_str}</strong></p>",
                unsafe_allow_html=True,
            )

        st.divider()

        # Auto-refresh
        st.markdown(
            "<p style='font-size:0.65rem;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:0.1em;font-weight:600;margin:0 0 0.45rem;'>Rafraîchissement</p>",
            unsafe_allow_html=True,
        )
        auto = st.toggle("Auto (5s)", value=False, key="auto_refresh")
        if st.button(
            "⟳  Rafraîchir maintenant", use_container_width=True, key="refresh_btn"
        ):
            st.cache_data.clear()
            st.rerun()

        st.divider()

        # Reset
        st.markdown(
            "<p style='font-size:0.65rem;color:#9ca3af;text-transform:uppercase;"
            "letter-spacing:0.1em;font-weight:600;margin:0 0 0.45rem;'>Gestion</p>",
            unsafe_allow_html=True,
        )
        if st.button(
            "🗑  Réinitialiser métriques",
            use_container_width=True,
            type="primary",
            key="reset_btn",
        ):
            if _reset_metrics():
                st.cache_data.clear()
                st.success("Métriques réinitialisées.")
                st.rerun()
            else:
                st.error("Erreur lors de la réinitialisation.")

        if auto:
            st.session_state["_auto_refresh"] = True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="Observabilité · SQL AI Agent",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_CSS, unsafe_allow_html=True)

    m = _fetch_metrics()
    _render_sidebar(m)

    # Header
    st.markdown(
        "<h1 style='font-size:1.35rem;font-weight:700;color:#18181b;"
        "letter-spacing:-0.025em;margin:0 0 0.15rem;font-family:Inter,sans-serif;'>"
        "📊 Tableau de bord — Observabilité</h1>"
        "<p style='color:#71717a;font-size:0.82rem;margin:0 0 1.2rem;"
        "font-family:Inter,sans-serif;'>Métriques temps réel de l'agent SQL</p>",
        unsafe_allow_html=True,
    )

    if m is None:
        st.error("API indisponible — impossible de récupérer les métriques.")
        st.stop()

    total = m.get("requests", {}).get("total", 0)
    if total == 0:
        st.info(
            "Aucune requête traitée pour l'instant. "
            "Envoyez des questions via l'interface principale pour voir les métriques."
        )

    _render_requests(m)
    _render_latency(m)
    _render_throughput(m)
    _render_tokens(m)
    _render_validation(m)
    _render_repair(m)
    _render_model(m)

    # Auto-refresh via rerun
    if st.session_state.get("_auto_refresh"):
        st.session_state["_auto_refresh"] = False
        time.sleep(5)
        st.cache_data.clear()
        st.rerun()


main()
