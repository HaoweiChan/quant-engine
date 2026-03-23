"""Dark terminal theme constants and Dash component builders.

Matches the visual language of docs/pyramid-position-engine.jsx:
deep navy backgrounds, JetBrains Mono numbers, color-coded P&L accents.
"""
from __future__ import annotations

from dash import dcc, html

# ── Color palette (layered charcoal – no pure-black / pure-white) ─────────
BG = "#0F1117"
SIDEBAR_BG = "#141721"
CARD_BG = "#1A1D28"
CARD_BORDER = "#2A2D3E"
INPUT_BG = "#1E2130"
INPUT_BORDER = "#353849"
GREEN = "#69f0ae"
RED = "#ff5252"
BLUE = "#5a8af2"
CYAN = "#4fc3f7"
PURPLE = "#ce93d8"
GOLD = "#ffd54f"
ORANGE = "#ff8a65"
LIGHT_BLUE = "#81d4fa"
MUTED = "#8B8FA3"
DIM = "#6B7280"
TEXT = "#E0E0E0"

# ── Fonts ───────────────────────────────────────────────────────────────────
MONO = "'JetBrains Mono', monospace"
SANS = "'IBM Plex Sans', system-ui, sans-serif"
SERIF = "'IBM Plex Serif', serif"

# ── Shared Plotly chart layout base ────────────────────────────────────────
DARK_CHART_LAYOUT: dict = {
    "paper_bgcolor": CARD_BG,
    "plot_bgcolor": CARD_BG,
    "font": {"family": MONO, "color": DIM, "size": 8},
    "xaxis": {
        "gridcolor": "#252838", "linecolor": "#2A2D3E",
        "zerolinecolor": "#353849", "tickfont": {"size": 8, "color": DIM},
    },
    "yaxis": {
        "gridcolor": "#252838", "linecolor": "#2A2D3E",
        "zerolinecolor": "#353849", "tickfont": {"size": 8, "color": DIM},
    },
    "margin": {"l": 50, "r": 14, "t": 28, "b": 28},
    "showlegend": False,
    "hovermode": "x unified",
    "hoverlabel": {
        "bgcolor": "rgba(20,23,33,0.96)", "bordercolor": "#353849",
        "font": {"family": MONO, "color": TEXT, "size": 10},
    },
}

# ── Layout geometry ─────────────────────────────────────────────────────────
SIDEBAR_STYLE: dict = {
    "width": 234, "minWidth": 234,
    "borderRight": f"1px solid {CARD_BORDER}",
    "padding": "10px 13px",
    "overflowY": "auto",
    "background": SIDEBAR_BG,
    "flexShrink": 0,
}

MAIN_STYLE: dict = {
    "flex": 1, "padding": "12px 20px",
    "overflowY": "auto", "minWidth": 0,
}

INPUT_STYLE: dict = {
    "width": "100%", "padding": "4px 6px",
    "background": INPUT_BG, "border": f"1px solid {INPUT_BORDER}",
    "borderRadius": 3, "color": TEXT,
    "fontSize": 11, "fontFamily": MONO,
    "outline": "none", "boxSizing": "border-box",
}

# ── HTML template with Google Fonts + global CSS ────────────────────────────
_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700"
    "&family=JetBrains+Mono:wght@400;500;700"
    "&family=IBM+Plex+Serif:wght@500;600&display=swap"
)

_GLOBAL_CSS = f"""
*, *::before, *::after {{ box-sizing: border-box; }}
body {{ background: {BG}; color: {TEXT}; font-family: {SANS}; margin: 0; padding: 0; min-height: 100vh; color-scheme: dark; }}
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: {BG}; }}
::-webkit-scrollbar-thumb {{ background: {INPUT_BORDER}; border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: #4a4d5e; }}
.Select-control {{ background-color: {INPUT_BG} !important; border-color: {INPUT_BORDER} !important; color: {TEXT} !important; font-family: {MONO} !important; font-size: 11px !important; }}
.Select-menu-outer {{ background-color: {SIDEBAR_BG} !important; border-color: {INPUT_BORDER} !important; }}
.Select-option {{ background-color: {SIDEBAR_BG} !important; color: {TEXT} !important; font-family: {MONO} !important; font-size: 11px !important; }}
.Select-option.is-focused {{ background-color: {INPUT_BG} !important; }}
.Select-option.is-selected {{ background-color: #253048 !important; }}
.Select-value-label {{ color: {TEXT} !important; }}
.Select-placeholder {{ color: {MUTED} !important; }}
.Select-arrow {{ border-top-color: {MUTED} !important; }}
.VirtualizedSelectOption {{ background: {SIDEBAR_BG} !important; color: {TEXT} !important; font-family: {MONO} !important; font-size: 11px !important; }}
.VirtualizedSelectFocusedOption {{ background: {INPUT_BG} !important; }}
.dash-dropdown-wrapper {{ font-family: {MONO} !important; font-size: 11px !important; }}
.dash-dropdown-trigger {{ background: {INPUT_BG} !important; border: 1px solid {INPUT_BORDER} !important; border-radius: 3px !important; color: {TEXT} !important; }}
.dash-dropdown-trigger:hover {{ border-color: #4a4d5e !important; }}
.dash-dropdown-value-item {{ color: {TEXT} !important; }}
.dash-dropdown-menu {{ background: {SIDEBAR_BG} !important; border: 1px solid {INPUT_BORDER} !important; }}
.dash-dropdown-option {{ background: {SIDEBAR_BG} !important; color: {TEXT} !important; font-family: {MONO} !important; font-size: 11px !important; }}
.dash-dropdown-option:hover, .dash-dropdown-option--focused {{ background: {INPUT_BG} !important; }}
.dash-dropdown-option--selected {{ background: #253048 !important; }}
.dash-dropdown-search-input {{ background: {INPUT_BG} !important; color: {TEXT} !important; caret-color: {TEXT} !important; }}
.dash-dropdown-search-wrapper {{ background: {INPUT_BG} !important; border-bottom: 1px solid {INPUT_BORDER} !important; }}
.dash-dropdown-search {{ background: {INPUT_BG} !important; }}
.dash-input-container {{ border: 1px solid {INPUT_BORDER} !important; border-radius: 3px !important; background: {INPUT_BG} !important; }}
.dash-input-stepper {{ background: {CARD_BORDER} !important; color: {TEXT} !important; border: none !important; min-width: 32px; cursor: pointer; }}
.dash-input-stepper:hover {{ background: #3a3d4e !important; }}
.dash-input-stepper svg {{ fill: {TEXT} !important; }}
.tab-container {{ display: flex !important; flex-direction: row !important; justify-content: center; }}
.tab {{ cursor: pointer; white-space: nowrap; }}
input[type="number"], input[type="text"],
input[type="number"]:focus, input[type="text"]:focus,
input[type="password"], input[type="password"]:focus {{
    background-color: {INPUT_BG} !important; border: 1px solid {INPUT_BORDER} !important;
    border-radius: 3px !important; color: {TEXT} !important; font-family: {MONO} !important;
    font-size: 11px !important; padding: 4px 6px !important; width: 100% !important;
    outline: none !important; box-shadow: none !important;
}}
[id*="editor-file-item"]:hover {{ background: {INPUT_BG}; color: {TEXT} !important; }}
.Select-input input {{ background: {INPUT_BG} !important; color: {TEXT} !important; }}
.Select-input {{ background: {INPUT_BG} !important; }}
input[type="search"] {{ background-color: {INPUT_BG} !important; color: {TEXT} !important; caret-color: {TEXT} !important; border: none !important; }}
.dash-dropdown input {{ background-color: {INPUT_BG} !important; color: {TEXT} !important; caret-color: {TEXT} !important; }}
/* Dash 4 — intercept every input inside any dropdown-ish container */
input[role="combobox"],
input[role="combobox"]:focus,
input[role="combobox"]:focus-visible,
input[role="combobox"]:active {{
    background-color: {INPUT_BG} !important;
    color: {TEXT} !important;
    caret-color: {TEXT} !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
    -webkit-appearance: none !important;
}}
/* Kill the white wrapper border that appears around the search box */
div:has(> input[role="combobox"]) {{
    background-color: {INPUT_BG} !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
}}
/* The container one level up (search row with magnifier icon) */
div:has(input[role="combobox"]) {{
    background-color: {INPUT_BG} !important;
    border: none !important;
    border-bottom: 1px solid {INPUT_BORDER} !important;
    outline: none !important;
    box-shadow: none !important;
}}
/* Nuke any nested wrapper that inherits white from a parent */
div:has(input[role="combobox"]) > * {{
    background-color: {INPUT_BG} !important;
    border: none !important;
    outline: none !important;
    box-shadow: none !important;
}}
/* Dash 4 react-select search wrapper */
div[class$="-Input"] input,
div[class*="-Input"] input,
div[class$="-input"] input,
.css-1g6gooi input,
.css-ackcql input {{
    background: {INPUT_BG} !important;
    color: {TEXT} !important;
    caret-color: {TEXT} !important;
}}
/* Dash 4 dropdown container backgrounds */
div[class$="-menu"],
div[class*="-menu"],
div[class*="menu"] {{
    background-color: {SIDEBAR_BG} !important;
    border: 1px solid {INPUT_BORDER} !important;
    border-radius: 4px !important;
}}
div[class$="-option"],
div[class*="-option"] {{
    background-color: {SIDEBAR_BG} !important;
    color: {TEXT} !important;
    font-family: {MONO} !important;
    font-size: 11px !important;
    cursor: pointer;
}}
div[class$="-option"]:hover,
div[class*="-option"]:hover,
div[class*="option--is-focused"] {{
    background-color: {INPUT_BG} !important;
}}
div[class*="option--is-selected"] {{
    background-color: #253048 !important;
}}
div[class$="-ValueContainer"],
div[class*="-ValueContainer"] {{
    background-color: {INPUT_BG} !important;
    border-radius: 4px !important;
}}
div[class$="-control"],
div[class*="-control"] {{
    background-color: {INPUT_BG} !important;
    border-color: {INPUT_BORDER} !important;
    border-radius: 4px !important;
    box-shadow: none !important;
    min-height: 28px !important;
}}
div[class$="-control"]:hover,
div[class*="-control"]:hover {{
    border-color: #4a4d5e !important;
}}
div[class$="-singleValue"],
div[class*="-singleValue"] {{
    color: {TEXT} !important;
    font-family: {MONO} !important;
    font-size: 11px !important;
}}
div[class$="-placeholder"],
div[class*="-placeholder"] {{
    color: {MUTED} !important;
    font-family: {MONO} !important;
    font-size: 11px !important;
}}
div[class$="-indicatorContainer"] svg,
div[class*="-indicatorContainer"] svg {{
    fill: {MUTED} !important;
    width: 14px !important;
    height: 14px !important;
}}
div[class$="-indicatorSeparator"],
div[class*="-indicatorSeparator"] {{
    background-color: {INPUT_BORDER} !important;
}}
/* Search icon inside dropdown */
svg[class*="search"], svg[aria-label="search"],
div:has(> input[role="combobox"]) ~ svg,
div:has(input[role="combobox"]) svg {{
    fill: {MUTED} !important;
    color: {MUTED} !important;
    opacity: 0.6;
    width: 12px !important;
    height: 12px !important;
}}
div[class$="-Input"],
div[class*="-Input"] {{
    background-color: {INPUT_BG} !important;
    color: {TEXT} !important;
}}
input:-webkit-autofill, input:-webkit-autofill:hover, input:-webkit-autofill:focus {{
    -webkit-box-shadow: 0 0 0 30px {INPUT_BG} inset !important;
    -webkit-text-fill-color: {TEXT} !important;
    transition: background-color 5000s ease-in-out 0s;
}}
"""

INDEX_STRING = (
    "<!DOCTYPE html><html><head>"
    "{%metas%}<title>{%title%}</title>{%favicon%}{%css%}"
    f'<link href="{_FONTS_URL}" rel="stylesheet">'
    f"<style>{_GLOBAL_CSS}</style>"
    "</head><body>"
    "{%app_entry%}"
    "<footer>{%config%}{%scripts%}{%renderer%}</footer>"
    "</body></html>"
)


# ── Component builders ──────────────────────────────────────────────────────
def stat_card(label: str, value: str, color: str, sub: str | None = None) -> html.Div:
    children: list = [
        html.Div(label, style={
            "fontSize": 7, "color": MUTED, "letterSpacing": "1px",
            "textTransform": "uppercase", "fontFamily": MONO, "marginBottom": 1,
        }),
        html.Div(value, style={"fontSize": 15, "fontWeight": 700, "color": color, "fontFamily": MONO}),
    ]
    if sub:
        children.append(html.Div(sub, style={"fontSize": 7, "color": DIM, "marginTop": 1}))
    return html.Div(children, style={
        "background": CARD_BG, "border": f"1px solid {CARD_BORDER}", "borderRadius": 5,
        "padding": "8px 10px", "flex": "1 1 90px", "minWidth": 90,
    })


def stat_row(cards: list) -> html.Div:
    return html.Div(cards, style={"display": "flex", "gap": 6, "flexWrap": "wrap", "marginBottom": 12})


def section_label(text: str) -> html.Div:
    return html.Div(text, style={
        "fontSize": 8, "color": MUTED, "letterSpacing": "1.5px",
        "textTransform": "uppercase", "fontFamily": MONO, "marginBottom": 6, "fontWeight": 700,
    })


def param_input(label: str, component: object) -> html.Div:
    return html.Div([
        html.Div(label, style={"fontSize": 9, "color": DIM, "fontFamily": MONO, "marginBottom": 1}),
        component,
    ], style={"marginBottom": 6})


def run_btn(label: str, btn_id: str, bg: str = "#2A5A9A") -> html.Button:
    return html.Button(label, id=btn_id, n_clicks=0, style={
        "width": "100%", "padding": "7px 0", "background": bg,
        "color": "#fff", "border": "none", "borderRadius": 3,
        "cursor": "pointer", "fontFamily": MONO, "fontSize": 10, "fontWeight": 600, "marginTop": 8,
    })


def chart_card(title: str, content: object, extra_style: dict | None = None) -> html.Div:
    style: dict = {
        "background": CARD_BG, "border": f"1px solid {CARD_BORDER}",
        "borderRadius": 6, "padding": "12px 8px 8px", "marginBottom": 10,
    }
    if extra_style:
        style.update(extra_style)
    return html.Div([
        html.Div(title, style={
            "fontSize": 9, "color": MUTED, "fontFamily": MONO,
            "marginBottom": 6, "paddingLeft": 4, "letterSpacing": "1px",
        }),
        content,
    ], style=style)


def dark_graph(figure: object, height: int = 280, graph_id: str | None = None) -> dcc.Graph:
    kwargs: dict = {"figure": figure, "config": {"displayModeBar": False}, "style": {"height": height}}
    if graph_id:
        kwargs["id"] = graph_id
    return dcc.Graph(**kwargs)


def dark_table_style() -> dict:
    """Return style props to spread into a dash_table.DataTable."""
    return {
        "style_header": {
            "backgroundColor": SIDEBAR_BG, "color": MUTED,
            "fontFamily": MONO, "fontSize": 9, "fontWeight": 500,
            "border": "none", "borderBottom": f"1px solid {CARD_BORDER}",
        },
        "style_cell": {
            "backgroundColor": CARD_BG, "color": TEXT,
            "fontFamily": MONO, "fontSize": 9,
            "border": f"1px solid {BG}", "padding": "4px 6px",
        },
        "style_data": {"backgroundColor": CARD_BG},
        "style_table": {"overflowX": "auto"},
    }


def error_card(message: str) -> html.Div:
    return html.Div(message, style={
        "border": f"1px solid {RED}", "borderRadius": 5,
        "padding": "12px 16px", "color": RED,
        "fontFamily": MONO, "fontSize": 11, "marginBottom": 10,
    })


def info_msg(message: str) -> html.Div:
    return html.Div(message, style={
        "color": MUTED, "fontFamily": MONO, "fontSize": 11, "padding": "20px 4px",
    })
