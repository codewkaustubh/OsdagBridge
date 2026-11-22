"""Report charts from stored design and material take-off results."""

import base64
import io
import json
import logging
import subprocess
import sys

from .styles import (
    CHART_NEUTRAL,
    CHART_PRIMARY,
    CHART_SECONDARY,
    CHART_TERTIARY,
    THRESHOLD_REFERENCE,
)

logger = logging.getLogger(__name__)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 and number < float("inf") else None


def _component_utilization_values(bridge):
    from osdagbridge.core.utils.common import (
        KEY_DD_MU_BOT,
        KEY_DD_MU_OH,
        KEY_DD_MU_TOP,
        KEY_DD_M_ULS_HOG,
        KEY_DD_M_ULS_OH,
        KEY_DD_M_ULS_SAG,
        KEY_DD_PUNCH_VED,
        KEY_DD_SHEAR_VED,
        KEY_DD_SHEAR_VRDC,
        KEY_DD_VRD_C_MPA,
        KEY_DD_WK_BOT,
        KEY_DD_WK_LIMIT,
        KEY_DD_WK_OH,
        KEY_DD_WK_TOP,
    )
    from osdagbridge.core.reports.executive_summary import _max_member_efficiency

    output_dict = bridge.output_dict
    per_girder = (output_dict.get("design_results", {}) or {}).get("per_girder", {}) or {}
    girder_urs = []
    steel_check_ids = {1, 2, 5, 8, 9, 11, 13, 14}
    for girder, data in per_girder.items():
        if str(girder).startswith("EB"):
            continue
        checks = list(data.get("checks") or [])
        if not checks:
            checks = [
                check
                for load_case in (data.get("per_lc") or {}).values()
                for check in (load_case.get("checks") or [])
            ]
        for check in checks:
            try:
                check_id = int(check.get("check_id", check.get("id")))
            except (TypeError, ValueError):
                continue
            if check_id in steel_check_ids:
                ur = _number(check.get("dcr"))
                if ur is not None:
                    girder_urs.append(ur)

    deck_results = output_dict.get("deck_design_results", {}) or {}
    deck_urs = [
        _number(value)
        for key, value in deck_results.items()
        if str(key).startswith("ur_")
    ]
    deck_urs = [value for value in deck_urs if value is not None]
    if not deck_urs:
        report_values = output_dict.get("deck_report_values", {}) or {}
        demand_capacity_pairs = (
            (KEY_DD_M_ULS_SAG, KEY_DD_MU_BOT),
            (KEY_DD_M_ULS_HOG, KEY_DD_MU_TOP),
            (KEY_DD_M_ULS_OH, KEY_DD_MU_OH),
            (KEY_DD_PUNCH_VED, KEY_DD_VRD_C_MPA),
            (KEY_DD_SHEAR_VED, KEY_DD_SHEAR_VRDC),
            (KEY_DD_WK_BOT, KEY_DD_WK_LIMIT),
            (KEY_DD_WK_TOP, KEY_DD_WK_LIMIT),
            (KEY_DD_WK_OH, KEY_DD_WK_LIMIT),
        )
        for demand_key, capacity_key in demand_capacity_pairs:
            demand = _number(report_values.get(demand_key))
            capacity = _number(report_values.get(capacity_key))
            if demand is not None and capacity is not None and capacity > 0:
                deck_urs.append(demand / capacity)

    return {
        "Steel Plate Girders": max(girder_urs) if girder_urs else None,
        "Concrete Deck Slab": max(deck_urs) if deck_urs else None,
        "Cross Bracing": _number(_max_member_efficiency(
            output_dict.get("crossbracing_design_results", {}) or {}
        )),
        "End Diaphragms": _number(_max_member_efficiency(
            output_dict.get("end_diaphragm_design_results", {}) or {}
        )),
    }


def _material_values(inputs):
    def numeric(key):
        return _number(inputs.get(key))

    bracing_parts = [
        numeric("bracing_top_wt_total"),
        numeric("bracing_bot_wt_total"),
        numeric("bracing_diag_wt_total"),
    ]
    bracing = (
        sum(value for value in bracing_parts if value is not None)
        if any(value is not None for value in bracing_parts)
        else numeric("steel_bracing_wt_total")
    )
    return {
        "steel_girders": numeric("steel_girders_wt_total"),
        "cross_bracing": bracing,
        "end_diaphragms": numeric("end_diaphragm_wt_total"),
        "concrete_deck": numeric("concrete_deck_vol_total"),
        "reinforcement": numeric("rebar_deck_wt_total"),
    }


def _chart_specs(bridge, inputs):
    utilization = _component_utilization_values(bridge)
    materials = _material_values(inputs)
    return {
        "ur_summary": {
            "title": "Overall Design Utilization Ratios",
            "ylabel": "Utilization Ratio (Demand / Capacity)",
            "labels": list(utilization),
            "values": list(utilization.values()),
            "reference": 1.0,
            "reference_color": THRESHOLD_REFERENCE,
            "suffix": "",
            "colors": [
                CHART_PRIMARY,
                CHART_SECONDARY,
                CHART_NEUTRAL,
                CHART_TERTIARY,
            ],
        },
        "material_steel": {
            "title": "Structural Steel Tonnage",
            "ylabel": "Structural steel weight (MT)",
            "labels": ["Girders", "Cross Bracing", "End Diaphragms"],
            "values": [
                materials["steel_girders"],
                materials["cross_bracing"],
                materials["end_diaphragms"],
            ],
            "suffix": " MT",
            "colors": [CHART_PRIMARY, CHART_SECONDARY, CHART_NEUTRAL],
        },
        "material_concrete_rebar": {
            "panels": [
                {
                    "title": "Concrete Deck Volume",
                    "ylabel": "m^3",
                    "labels": ["Concrete Deck"],
                    "values": [materials["concrete_deck"]],
                    "suffix": " m^3",
                    "colors": [CHART_SECONDARY],
                },
                {
                    "title": "Reinforcement Steel",
                    "ylabel": "MT",
                    "labels": ["Reinforcement"],
                    "values": [materials["reinforcement"]],
                    "suffix": " MT",
                    "colors": [CHART_TERTIARY],
                },
            ],
        },
    }


_MATPLOTLIB_RENDERER = r"""
import base64
import io
import json
import sys

import matplotlib
matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt

specs = json.loads(sys.argv[1])
rendered = {}

def render_axis(axis, spec):
    labels = spec["labels"]
    values = spec["values"]
    heights = [value if value is not None else 0.0 for value in values]
    colors = spec["colors"]
    bars = axis.bar(labels, heights, color=colors[:len(labels)])
    reference = spec.get("reference")
    if reference is not None:
        axis.axhline(reference, color=spec.get("reference_color", "#D32F2F"),
                     linestyle="--", linewidth=1.6,
                     label="UR = 1.0 (capacity)")
        axis.legend(loc="upper left")
    for bar, value, suffix in zip(bars, values, [spec.get("suffix", "")] * len(values)):
        text = f"{value:.2f}{suffix}" if value is not None else "N/A"
        axis.annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                      xytext=(0, 4), textcoords="offset points", ha="center",
                      va="bottom")
    axis.set_ylabel(spec.get("ylabel", ""))
    axis.set_title(spec["title"])
    axis.grid(axis="y", alpha=0.25)
    axis.tick_params(axis="x", labelrotation=12)
    maximum = max([reference or 0.0] + [value for value in values if value is not None])
    axis.set_ylim(0, maximum * 1.18 + 0.08)

for name, spec in specs.items():
    if "panels" in spec:
        figure, axes = plt.subplots(1, len(spec["panels"]), figsize=(9, 3.8),
                                    constrained_layout=True)
        for axis, panel in zip(axes, spec["panels"]):
            render_axis(axis, panel)
    else:
        figure, axis = plt.subplots(figsize=(9, 4.2), constrained_layout=True)
        render_axis(axis, spec)
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=140, bbox_inches="tight")
    rendered[name] = base64.b64encode(buffer.getvalue()).decode("ascii")
    plt.close(figure)

sys.stdout.write(json.dumps(rendered))
"""


def _draw_pillow_chart(spec, size=(1100, 520)):
    from PIL import Image, ImageDraw, ImageFont

    width, height = size
    left = max(60, int(width * 0.095))
    right = max(22, int(width * 0.04))
    top, bottom = 80, 145
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    draw.text((left, 24), spec["title"], fill="#222222", font=font)

    labels = spec["labels"]
    values = spec["values"]
    reference = spec.get("reference")
    maximum = max(
        [reference or 0.0, 0.5]
        + [value for value in values if value is not None]
    )
    scale_max = maximum * 1.15
    chart_bottom = height - bottom
    chart_height = chart_bottom - top
    chart_width = width - left - right
    for tick in range(6):
        value = scale_max * tick / 5
        y = chart_bottom - int(chart_height * tick / 5)
        draw.line((left, y, width - right, y), fill="#dddddd", width=1)
        draw.text((left - 55, y - 6), f"{value:.1f}", fill="#555555", font=font)

    if reference is not None:
        y = chart_bottom - int(chart_height * reference / scale_max)
        for x in range(left, width - right, 16):
            draw.line((x, y, min(x + 9, width - right), y), fill=THRESHOLD_REFERENCE, width=2)
        draw.text((left + 8, y - 16), "UR = 1.0 (capacity)", fill=THRESHOLD_REFERENCE, font=font)

    colors = spec["colors"]
    count = max(1, len(labels))
    slot = chart_width / count
    bar_width = min(115, slot * 0.58)
    for index, (label, value) in enumerate(zip(labels, values)):
        center = left + slot * (index + 0.5)
        bar_height = int(chart_height * (value or 0.0) / scale_max)
        x1 = int(center - bar_width / 2)
        x2 = int(center + bar_width / 2)
        y1 = chart_bottom - bar_height
        if value is not None and value > 0:
            draw.rectangle((x1, y1, x2, chart_bottom), fill=colors[index % len(colors)])
        value_label = f"{value:.2f}{spec.get('suffix', '')}" if value is not None else "N/A"
        draw.text((int(center - 30), max(top, y1 - 20)), value_label, fill="#222222", font=font)
        words = label.split()
        lines = []
        current = ""
        for word in words:
            candidate = (current + " " + word).strip()
            if len(candidate) > 16 and current:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        for line_index, line in enumerate(lines):
            draw.text(
                (int(center - len(line) * 3), chart_bottom + 16 + 17 * line_index),
                line,
                fill="#333333",
                font=font,
            )
    draw.line((left, top, left, chart_bottom), fill="#444444", width=2)
    draw.line((left, chart_bottom, width - right, chart_bottom), fill="#444444", width=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _render_with_pillow(specs):
    rendered = {}
    for name, spec in specs.items():
        if "panels" not in spec:
            rendered[name] = _draw_pillow_chart(spec)
            continue

        panel_images = [
            _draw_pillow_chart(panel, size=(550, 520))
            for panel in spec["panels"]
        ]
        from PIL import Image

        images = [Image.open(io.BytesIO(data)).convert("RGB") for data in panel_images]
        panel_width = images[0].width
        panel_height = max(image.height for image in images)
        combined = Image.new("RGB", (panel_width * len(images), panel_height), "white")
        for index, image in enumerate(images):
            combined.paste(image, (index * panel_width, 0))
        buffer = io.BytesIO()
        combined.save(buffer, format="PNG")
        rendered[name] = buffer.getvalue()
    return rendered


def render_report_charts(bridge, inputs):
    """Render report charts with Matplotlib, isolating native backend failures."""
    specs = _chart_specs(bridge, inputs)
    command = [sys.executable, "-c", _MATPLOTLIB_RENDERER, json.dumps(specs)]
    kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "check": False,
        "timeout": 60,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired:
        logger.warning("Matplotlib report chart rendering timed out; using Pillow fallback.")
    except OSError as exc:
        logger.warning("Matplotlib report chart renderer could not start: %s", exc)
    else:
        if result.returncode == 0:
            try:
                encoded = json.loads(result.stdout.decode("utf-8"))
                return {
                    name: base64.b64decode(image)
                    for name, image in encoded.items()
                }
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Matplotlib returned invalid chart data: %s", exc)
        else:
            detail = result.stderr.decode("utf-8", "replace").strip()
            logger.warning(
                "Matplotlib report chart renderer exited with code %s; using Pillow fallback. %s",
                result.returncode,
                detail[-1200:],
            )
    return _render_with_pillow(specs)
