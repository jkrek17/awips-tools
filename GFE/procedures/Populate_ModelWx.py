"""
Marine Weather Grid Builder - Comprehensive Wx grid creation tool.

Builds weather grids from atmospheric model data including precipitation,
thunderstorms, and fog. Uses shared utilities for model access.

Modular rewrite using shared utilities for model aliases and thresholds.
"""

from __future__ import annotations

import tkinter as tk
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import ndimage

import SmartScript
from WxMethods import *

import grid_fetch
import gui
import model_aliases
import thresholds

MenuItems = ["Populate"]
VariableList = []

# Available atmospheric models
ATMOSPHERIC_MODELS = ["GFS", "ECMWF", "CMC", "UKMET"]
FREEZING_C = 0.0
SNOW_QPF_SCALE = 1.5
MODEL_WX_TEXTURE = {
    "window": 9,
    "stratiform_max": 0.4,
    "convective_min": 0.8,
    "cape_stratiform_max": 300.0,
    "cape_convective_min": 800.0,
    "eps": 1e-6,
}
ICE_ACCRETION_CFG = {
    "seawater_freezing_c": -1.7,
    "sst_valid_f": 25.0,
    "light_min": 0.1,
    "moderate_min": 0.7,
    "heavy_min": 2.0,
    "max": 5.0,
    "edit_area": "OPC_AOR",
    "wx_coverage": "Sct",
    "wx_type": "ZY",
}


def _get_safe_qpf_cfg() -> Dict[str, float]:
    return getattr(
        thresholds,
        "get_model_wx_qpf_thresholds",
        lambda: {
            "minimum_in": 0.01,
            "light_in": 0.05,
            "moderate_in": 0.25,
            "heavy_in": 0.50,
            "coverage_wide_in": 0.25,
            "coverage_numerous_in": 0.10,
            "coverage_scattered_in": 0.03,
            "prob_definite_in": 0.25,
            "prob_likely_in": 0.10,
            "prob_chance_in": 0.03,
            "severe_with_thunder_in": 1.0,
        },
    )()


def _get_safe_convection_cfg() -> Dict[str, float]:
    return getattr(
        thresholds,
        "get_model_wx_convection",
        lambda: {"convective_index_threshold": 7.0},
    )()


def _get_safe_texture_cfg() -> Dict[str, float]:
    return dict(MODEL_WX_TEXTURE)


def _get_safe_fog_cfg() -> Dict[str, float]:
    return getattr(
        thresholds,
        "get_model_wx_fog_thresholds_nm",
        lambda: {
            "visibility_default_nm": 2.6,
            "visibility_min_nm": 0.4,
            "visibility_max_nm": 5.2,
            "relative_humidity_min_pct": 85.0,
        },
    )()


def _compute_qpf_texture(
    qpf_raw: np.ndarray, window: int, eps: float
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (texture, mean) from unsmoothed QPF (higher texture = noisier)."""
    if window < 3:
        window = 3
    if window % 2 == 0:
        window += 1
    qpf_clip = np.maximum(qpf_raw, 0.0)
    mean = ndimage.uniform_filter(qpf_clip, size=window, mode="nearest")
    mean_sq = ndimage.uniform_filter(qpf_clip * qpf_clip, size=window, mode="nearest")
    var = np.maximum(mean_sq - mean * mean, 0.0)
    std = np.sqrt(var)
    texture = std / (mean + eps)
    return texture, mean


def _compute_ice_accretion(
    temp_c: np.ndarray,
    sst_f: np.ndarray,
    wind_kt: np.ndarray,
    cfg: Dict[str, float],
) -> np.ndarray:
    """Compute ice accretion potential (Overland algorithm)."""
    tf_c = float(cfg.get("seawater_freezing_c", -1.7))
    try:
        sst_c = thresholds.f_to_c(sst_f)
    except AttributeError:
        sst_c = (sst_f - 32.0) * 5.0 / 9.0
    try:
        wind_ms = thresholds.to_mps(wind_kt)
    except AttributeError:
        wind_ms = wind_kt * 0.514444
    da = tf_c - temp_c
    dw = sst_c - tf_c
    denom = 1.0 + (0.3 * dw)
    denom = np.where(np.abs(denom) < 1e-6, 1e-6, denom)
    return (wind_ms * da) / denom


def _get_safe_smoothing_cfg() -> Dict[str, float]:
    return getattr(
        thresholds,
        "get_model_wx_smoothing_defaults",
        lambda: {"recommended": 10.0, "min": 0.0, "max": 20.0, "sigma": 0.7},
    )()


def _get_safe_clip_cfg() -> Dict[str, float]:
    try:
        return thresholds.get_diagnostic_clipping()
    except Exception:
        return {
            "qpf_max_in": 10.0,
            "cape_max": 8000.0,
            "temp_min_f": -50.0,
            "temp_max_f": 150.0,
            "rh_min_pct": 0.0,
            "rh_max_pct": 100.0,
            "vis_min_nm": 0.0,
            "vis_max_nm": 8.0,
            "wind_min_kt": 0.0,
            "wind_max_kt": 150.0,
            "conv_index_min": 0.0,
            "conv_index_max": 10.0,
        }


def _get_safe_cape_cfg(thunder_override: float) -> Dict[str, float]:
    default_cape = {
        "thunder_min": 500.0,
        "severe_min": 3000.0,
        "high": 2000.0,
        "moderate": 1000.0,
    }
    cape_cfg = getattr(thresholds, "get_cape_thresholds", lambda: default_cape)()
    cape_cfg["thunder_min"] = max(thunder_override, cape_cfg.get("thunder_min", thunder_override))
    return cape_cfg


class MarineWeatherGUI:
    """GUI for marine weather grid builder."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Weather Grid Builder")
        self.master.geometry("1250x1020")
        self.master.minsize(1100, 900)

        self._build_ui()

    def _build_ui(self):
        main = tk.Frame(self.master, padx=15, pady=15)
        main.pack(fill=tk.BOTH, expand=True)

        # Title
        tk.Label(main, text="Marine Weather Grid Builder",
                 font=("Arial", 16, "bold")).pack(pady=(0, 5))
        tk.Label(main, text="Precipitation • Thunderstorms • Fog",
                 font=("Arial", 10), fg="gray").pack(pady=(0, 5))
        tk.Label(
            main,
            text="Pick 1–4 models, choose build mode, set thresholds, then Run.",
            font=("Arial", 9),
            fg="gray",
        ).pack(pady=(0, 15))

        content = gui.TwoColumnLayout(main, padx=20)
        content.pack(fill=tk.BOTH, expand=True)

        # Left column: model selection + tuners
        self._build_model_frame(content.left)
        self._build_mode_frame(content.left)
        self._build_basic_params_frame(content.left)

        # Right column: QPF + run/diagnostics
        self._build_precip_frame(content.right)

        # Buttons
        self._build_buttons(main)

        self._update_selection()

    def _build_model_frame(self, parent):
        # Use ModelSelectionFrame from gui.py
        model_list = [(alias, alias) for alias in ATMOSPHERIC_MODELS]
        self.model_frame = gui.ModelSelectionFrame(
            parent,
            title="Select Atmospheric Models",
            models=model_list,
            default_selected=["GFS"],
            on_change=self._update_selection,
        )
        self.model_frame.pack(fill=tk.X, pady=(0, 10))

        # Add tip label
        tk.Label(
            self.model_frame,
            text="Tip: Start with GFS + one other global; add ECMWF for heavier events.",
            font=("Arial", 9),
            fg="gray",
            wraplength=420,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

        # Use StatusBanner from gui.py
        self.status_banner = gui.StatusBanner(self.model_frame)
        self.status_banner.pack(pady=(10, 0))

    def _build_mode_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Build Mode", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))
        
        self.build_mode_group = gui.RadioGroup(
            frame,
            options=[
                ("Build New (Replace All)", "Build New (Replace All)"),
                ("Enhance Existing", "Enhance Existing"),
            ],
            default="Build New (Replace All)",
        )
        self.build_mode_group.pack(anchor=tk.W)
        
        tk.Label(
            frame,
            text="Build New overwrites Wx; Enhance tweaks existing Wx while preserving other types.",
            font=("Arial", 9),
            fg="gray",
            wraplength=420,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))

    def _build_basic_params_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Analysis Parameters", padx=15, pady=10)
        frame.pack(fill=tk.X, pady=(0, 10))

        # Smoothing - use SmoothingSlider from gui.py
        try:
            smoothing_defaults = _get_safe_smoothing_cfg()
            default_val = int(round(smoothing_defaults.get("recommended", 10.0)))
            min_val = int(round(smoothing_defaults.get("min", 0.0)))
            max_val = int(round(smoothing_defaults.get("max", 20.0)))
        except (AttributeError, KeyError):
            default_val = 10
            min_val = 0
            max_val = 20
        self.smoothing_slider = gui.SmoothingSlider(
            frame,
            min_value=min_val,
            max_value=max_val,
            default=default_val,
            label="Spatial Smoothing:",
        )
        self.smoothing_slider.pack(anchor=tk.W)

        # Thunder CAPE threshold - use ThresholdSlider from gui.py
        try:
            thunder_default = int(getattr(thresholds, "CAPE_THRESHOLDS", {}).get("thunder_min", 500.0))
        except (AttributeError, KeyError):
            thunder_default = 500
        self.thunder_slider = gui.ThresholdSlider(
            frame,
            label="Thunder CAPE Threshold (J/kg):",
            min_value=100,
            max_value=1500,
            default=thunder_default,
            resolution=50,
            var_type=int,
        )
        self.thunder_slider.pack(anchor=tk.W, pady=(10, 0))

        # Fog threshold - use ThresholdSlider from gui.py
        try:
            fog_defaults = _get_safe_fog_cfg()
            vis_default_nm = fog_defaults.get("visibility_default_nm", 2.6)
            vis_min_nm = fog_defaults.get("visibility_min_nm", 0.4)
            vis_max_nm = fog_defaults.get("visibility_max_nm", 5.2)
        except (AttributeError, KeyError):
            vis_default_nm = 2.6
            vis_min_nm = 0.4
            vis_max_nm = 5.2
        self.fog_slider = gui.ThresholdSlider(
            frame,
            label="Fog Visibility Threshold (NM):",
            min_value=vis_min_nm,
            max_value=vis_max_nm,
            default=vis_default_nm,
            resolution=0.5,
            var_type=float,
        )
        self.fog_slider.pack(anchor=tk.W, pady=(10, 0))

    def _build_precip_frame(self, parent):
        frame = tk.LabelFrame(parent, text="Precipitation Parameters", padx=15, pady=10)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # QPF thresholds (inches / 3-hr)
        qpf_defaults = _get_safe_qpf_cfg()
        tk.Label(frame, text="QPF Thresholds (inches / ~3hr):", font=("Arial", 10, "bold")).pack(
            anchor=tk.W, pady=(12, 0)
        )
        tk.Label(
            frame,
            text="These thresholds control stratiform probability (Chc/Lkly/Def) and convective coverage (Iso/Sct/Num/Wide).",
            font=("Arial", 9),
            fg="gray",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 6))

        qpf_layout = gui.TwoColumnLayout(frame, padx=18)
        qpf_layout.pack(fill=tk.X)

        # Left: convective coverage thresholds
        tk.Label(qpf_layout.left, text="Convective coverage", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.qpf_min_slider = gui.ThresholdSlider(
            qpf_layout.left,
            label="Minimum precip (has_precip):",
            min_value=0.0,
            max_value=0.10,
            default=float(qpf_defaults.get("minimum_in", 0.01)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_min_slider.pack(anchor=tk.W)
        self.qpf_cov_scattered_slider = gui.ThresholdSlider(
            qpf_layout.left,
            label="Scattered (Sct) ≥",
            min_value=0.0,
            max_value=0.50,
            default=float(qpf_defaults.get("coverage_scattered_in", 0.03)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_cov_scattered_slider.pack(anchor=tk.W, pady=(6, 0))
        self.qpf_cov_numerous_slider = gui.ThresholdSlider(
            qpf_layout.left,
            label="Numerous (Num) ≥",
            min_value=0.0,
            max_value=1.00,
            default=float(qpf_defaults.get("coverage_numerous_in", 0.10)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_cov_numerous_slider.pack(anchor=tk.W, pady=(6, 0))
        self.qpf_cov_wide_slider = gui.ThresholdSlider(
            qpf_layout.left,
            label="Widespread (Wide) ≥",
            min_value=0.0,
            max_value=2.00,
            default=float(qpf_defaults.get("coverage_wide_in", 0.25)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_cov_wide_slider.pack(anchor=tk.W, pady=(6, 0))

        # Right: stratiform probability thresholds
        tk.Label(qpf_layout.right, text="Stratiform probability", font=("Arial", 9, "bold")).pack(anchor=tk.W)
        self.qpf_prob_chance_slider = gui.ThresholdSlider(
            qpf_layout.right,
            label="Chance (Chc) ≥",
            min_value=0.0,
            max_value=0.50,
            default=float(qpf_defaults.get("prob_chance_in", 0.03)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_prob_chance_slider.pack(anchor=tk.W)
        self.qpf_prob_likely_slider = gui.ThresholdSlider(
            qpf_layout.right,
            label="Likely (Lkly) ≥",
            min_value=0.0,
            max_value=1.00,
            default=float(qpf_defaults.get("prob_likely_in", 0.10)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_prob_likely_slider.pack(anchor=tk.W, pady=(6, 0))
        self.qpf_prob_definite_slider = gui.ThresholdSlider(
            qpf_layout.right,
            label="Definite (Def) ≥",
            min_value=0.0,
            max_value=2.00,
            default=float(qpf_defaults.get("prob_definite_in", 0.25)),
            resolution=0.01,
            var_type=float,
        )
        self.qpf_prob_definite_slider.pack(anchor=tk.W, pady=(6, 0))

        # Model Run - use RadioGroup from gui.py
        tk.Label(frame, text="Model Run:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.model_run_group = gui.RadioGroup(
            frame,
            options=[
                ("Current", "Current"),
                ("Previous", "Previous"),
            ],
            default="Current",
            orientation="horizontal",
        )
        self.model_run_group.pack(anchor=tk.W)

        # Diagnostics - use RadioGroup from gui.py
        tk.Label(frame, text="Create Diagnostic Grids:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.diagnostics_group = gui.RadioGroup(
            frame,
            options=[
                ("No", "No"),
                ("Yes", "Yes"),
            ],
            default="No",
            orientation="horizontal",
        )
        self.diagnostics_group.pack(anchor=tk.W)

        # QPF texture controls
        texture_defaults = _get_safe_texture_cfg()
        tk.Label(frame, text="QPF Texture (Uniform vs Noisy):", font=("Arial", 10, "bold")).pack(
            anchor=tk.W, pady=(12, 0)
        )
        tk.Label(
            frame,
            text="Lower texture favors stratiform (probability); higher texture favors convective (coverage).",
            font=("Arial", 9),
            fg="gray",
            wraplength=520,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 6))
        self.texture_window_slider = gui.ThresholdSlider(
            frame,
            label="Texture window (odd grid points):",
            min_value=3,
            max_value=21,
            default=float(texture_defaults.get("window", 9)),
            resolution=2,
            var_type=int,
        )
        self.texture_window_slider.pack(anchor=tk.W)
        self.texture_strat_slider = gui.ThresholdSlider(
            frame,
            label="Stratiform max (uniform):",
            min_value=0.1,
            max_value=1.0,
            default=float(texture_defaults.get("stratiform_max", 0.4)),
            resolution=0.05,
            var_type=float,
        )
        self.texture_strat_slider.pack(anchor=tk.W, pady=(6, 0))
        self.texture_conv_slider = gui.ThresholdSlider(
            frame,
            label="Convective min (noisy):",
            min_value=0.2,
            max_value=1.5,
            default=float(texture_defaults.get("convective_min", 0.8)),
            resolution=0.05,
            var_type=float,
        )
        self.texture_conv_slider.pack(anchor=tk.W, pady=(6, 0))

        # Output options
        self.output_options = gui.CheckboxGroup(
            frame,
            title="Output Options",
            options=[
                ("COPY_FOG_VIS", "Copy fog into Visibility grid"),
                ("CREATE_ICE_GRID", "Create IceAccretion grid"),
            ],
            default_selected=["COPY_FOG_VIS", "CREATE_ICE_GRID"],
        )
        self.output_options.pack(fill=tk.X, pady=(10, 0))

    def _build_buttons(self, parent):
        self.button_frame = gui.ButtonFrame(
            parent,
            run_text="Build Weather Grids",
            run_command=self._run,
            cancel_command=self._cancel,
            run_color="lightblue",
        )
        self.button_frame.pack(fill=tk.X, pady=(15, 0))

    def _update_selection(self, selected_models=None):
        if selected_models is None:
            selected_models = self.model_frame.get_selected_models()
        count = len(selected_models)
        if count == 0:
            self.status_banner.set_status("No Models Selected", "red")
            self.status_banner.set_message("Select at least one model", "red")
        else:
            self.status_banner.set_status(f"{count} Model(s) Selected", "green")
            self.status_banner.set_message("Ready to build weather grids", "green")

    def _run(self):
        selected = self.model_frame.get_selected_models()
        if not selected:
            self.status_banner.set_status("ERROR: Select at least 1 model!", "red")
            self.status_banner.set_message("", "red")
            return

        self.callback({
            "models": selected,
            "build_mode": self.build_mode_group.get_value(),
            "smoothing": self.smoothing_slider.get_value(),
            "thunder_thresh": int(self.thunder_slider.get_value()),
            "fog_thresh": self.fog_slider.get_value(),
            "qpf_minimum_in": float(self.qpf_min_slider.get_value()),
            "qpf_cov_scattered_in": float(self.qpf_cov_scattered_slider.get_value()),
            "qpf_cov_numerous_in": float(self.qpf_cov_numerous_slider.get_value()),
            "qpf_cov_wide_in": float(self.qpf_cov_wide_slider.get_value()),
            "qpf_prob_chance_in": float(self.qpf_prob_chance_slider.get_value()),
            "qpf_prob_likely_in": float(self.qpf_prob_likely_slider.get_value()),
            "qpf_prob_definite_in": float(self.qpf_prob_definite_slider.get_value()),
            "model_run": self.model_run_group.get_value(),
            "create_diagnostics": self.diagnostics_group.get_value(),
            "texture_window": int(self.texture_window_slider.get_value()),
            "texture_strat_max": float(self.texture_strat_slider.get_value()),
            "texture_conv_min": float(self.texture_conv_slider.get_value()),
            "copy_fog_visibility": self.output_options.get_value("COPY_FOG_VIS"),
            "create_ice_grid": self.output_options.get_value("CREATE_ICE_GRID"),
        })
        self.master.destroy()

    def _cancel(self):
        self.callback(None)
        self.master.destroy()


class Procedure(SmartScript.SmartScript):
    """Marine weather grid builder using shared utilities."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)
        self.output_log: List[str] = []

    def _show_results_popup(self):
        """Show results popup with all log output after execution."""
        try:
            # Collect all log messages
            output_text = "\n".join(self.output_log) if self.output_log else "No output generated."

            # Create a closeable window.
            # In AWIPS/GFE, tk._default_root may exist but not be running a mainloop,
            # so we use wait_window() to ensure events are processed until close.
            parent = getattr(tk, "_default_root", None)
            owns_root = False

            try:
                if parent is not None and int(parent.winfo_exists()):
                    win = tk.Toplevel(parent)
                else:
                    raise RuntimeError("No valid Tk root available")
            except Exception:
                win = tk.Tk()
                owns_root = True

            def _close():
                try:
                    win.destroy()
                except Exception:
                    pass

            win.title("Tool Execution Results")
            win.protocol("WM_DELETE_WINDOW", _close)
            win.bind("<Escape>", lambda e: _close())

            # Create popup content
            gui.ResultsPopup(win, "Tool Execution Results", output_text, readonly=True)

            # Bring to front
            try:
                win.lift()
                win.focus_force()
            except Exception:
                pass

            # Run a local event loop until closed.
            if owns_root:
                win.mainloop()
            else:
                win.wait_window()
        except Exception as e:
            self.statusBarMsg(f"Could not create results popup: {e}", "S")
            print(f"Could not create results popup: {e}")
            import traceback
            traceback.print_exc()

    def log(self, message: str):
        """Log message to console and collector."""
        print(message)
        self.output_log.append(message)

    def execute(self, editArea, timeRange, varDict=None):
        """Main execution method."""
        self.output_log = []

        if varDict is None:
            varDict = self._show_gui()
            if varDict is None:
                self.statusBarMsg("Build cancelled", "S")
                return

        models = varDict["models"]
        build_mode = varDict.get("build_mode", "Build New (Replace All)")
        smoothing = varDict["smoothing"]
        thunder_thresh = varDict["thunder_thresh"]
        fog_thresh = varDict["fog_thresh"]
        model_run = varDict["model_run"]
        create_diag = varDict["create_diagnostics"] == "Yes"
        copy_fog_visibility = bool(varDict.get("copy_fog_visibility", True))
        create_ice_grid = bool(varDict.get("create_ice_grid", True))

        qpf_cfg = _get_safe_qpf_cfg()
        # Apply user overrides from GUI (if present)
        for key, cfg_key in (
            ("qpf_minimum_in", "minimum_in"),
            ("qpf_cov_scattered_in", "coverage_scattered_in"),
            ("qpf_cov_numerous_in", "coverage_numerous_in"),
            ("qpf_cov_wide_in", "coverage_wide_in"),
            ("qpf_prob_chance_in", "prob_chance_in"),
            ("qpf_prob_likely_in", "prob_likely_in"),
            ("qpf_prob_definite_in", "prob_definite_in"),
        ):
            if key in varDict and varDict[key] is not None:
                try:
                    qpf_cfg[cfg_key] = float(varDict[key])
                except Exception:
                    pass

        # Enforce monotonic ordering to avoid impossible qualifier thresholds.
        # - Convective coverage: scattered <= numerous <= wide
        cov_sorted = sorted(
            [
                float(qpf_cfg.get("coverage_scattered_in", 0.03)),
                float(qpf_cfg.get("coverage_numerous_in", 0.10)),
                float(qpf_cfg.get("coverage_wide_in", 0.25)),
            ]
        )
        qpf_cfg["coverage_scattered_in"], qpf_cfg["coverage_numerous_in"], qpf_cfg["coverage_wide_in"] = cov_sorted

        # - Stratiform probability: chance <= likely <= definite
        prob_sorted = sorted(
            [
                float(qpf_cfg.get("prob_chance_in", 0.03)),
                float(qpf_cfg.get("prob_likely_in", 0.10)),
                float(qpf_cfg.get("prob_definite_in", 0.25)),
            ]
        )
        qpf_cfg["prob_chance_in"], qpf_cfg["prob_likely_in"], qpf_cfg["prob_definite_in"] = prob_sorted

        # - Minimum precip should not exceed the smallest qualifier threshold.
        try:
            qpf_cfg["minimum_in"] = min(
                float(qpf_cfg.get("minimum_in", 0.01)),
                float(qpf_cfg["coverage_scattered_in"]),
                float(qpf_cfg["prob_chance_in"]),
            )
        except Exception:
            pass
        conv_cfg = _get_safe_convection_cfg()
        texture_cfg = _get_safe_texture_cfg()
        ice_cfg = dict(ICE_ACCRETION_CFG)
        cape_cfg = _get_safe_cape_cfg(thunder_thresh)
        cape_cfg["thunder_min"] = max(thunder_thresh, cape_cfg.get("thunder_min", thunder_thresh))
        fog_cfg = _get_safe_fog_cfg()
        fog_rh_min = fog_cfg.get(
            "relative_humidity_min_pct",
            getattr(thresholds, "FOG_THRESHOLDS", {}).get("relative_humidity_min", 85.0),
        )
        conv_idx_thresh = conv_cfg.get("convective_index_threshold", 7.0)
        texture_window = int(texture_cfg.get("window", 9))
        texture_strat_max = float(texture_cfg.get("stratiform_max", 0.4))
        texture_conv_min = float(texture_cfg.get("convective_min", 0.8))
        cape_strat_max = float(texture_cfg.get("cape_stratiform_max", 300.0))
        cape_conv_min = float(texture_cfg.get("cape_convective_min", 800.0))
        texture_eps = float(texture_cfg.get("eps", 1e-6))
        if varDict.get("texture_window") is not None:
            try:
                texture_window = int(varDict["texture_window"])
            except Exception:
                pass
        if varDict.get("texture_strat_max") is not None:
            try:
                texture_strat_max = float(varDict["texture_strat_max"])
            except Exception:
                pass
        if varDict.get("texture_conv_min") is not None:
            try:
                texture_conv_min = float(varDict["texture_conv_min"])
            except Exception:
                pass
        if texture_window < 3:
            texture_window = 3
        if texture_window % 2 == 0:
            texture_window += 1
        if texture_strat_max < 0.0:
            texture_strat_max = 0.0
        if texture_conv_min < texture_strat_max:
            texture_conv_min = texture_strat_max
        ice_light_min = float(ice_cfg.get("light_min", 0.1))
        ice_moderate_min = float(ice_cfg.get("moderate_min", 0.7))
        ice_heavy_min = float(ice_cfg.get("heavy_min", 2.0))
        ice_max = float(ice_cfg.get("max", 5.0))
        ice_sst_min_f = float(ice_cfg.get("sst_valid_f", 25.0))
        ice_area_name = str(ice_cfg.get("edit_area", "OPC_AOR"))
        ice_cov = str(ice_cfg.get("wx_coverage", "Sct"))
        ice_type = str(ice_cfg.get("wx_type", "ZY"))
        # Try to honor IceAccretion element bounds if available
        try:
            parm = self.getParm("Fcst", "IceAccretion", "SFC")
            info = parm.getGridInfo()
            for attr in ("getMaxValue", "maxValue", "getMaxAllowedValue"):
                getter = getattr(info, attr, None)
                if callable(getter):
                    val = getter()
                    if val is not None:
                        ice_max = float(val)
                        break
            del parm
        except Exception:
            pass
        smoothing_cfg = _get_safe_smoothing_cfg()
        sigma_base = smoothing_cfg.get("sigma", 0.7)
        precip_min = float(qpf_cfg.get("minimum_in", 0.01))
        diag_clip = _get_safe_clip_cfg()

        run_depth = 1 if model_run == "Current" else 2

        self.log("="*80)
        self.log("MARINE WEATHER GRID BUILDER")
        self.log("="*80)
        self.log(f"Models: {', '.join(models)}")
        self.log(f"Build Mode: {build_mode}")
        self.log(f"Thunder Threshold: {thunder_thresh} J/kg")
        self.log(f"Fog Threshold: {fog_thresh} NM")
        self.log(f"Convective Index Threshold: {conv_idx_thresh}")
        self.log(
            "QPF thresholds (in): "
            f"min={qpf_cfg.get('minimum_in', 0.01):.2f}, "
            f"cov(Sct/Num/Wide)={qpf_cfg.get('coverage_scattered_in', 0.03):.2f}/"
            f"{qpf_cfg.get('coverage_numerous_in', 0.10):.2f}/"
            f"{qpf_cfg.get('coverage_wide_in', 0.25):.2f}, "
            f"prob(Chc/Lkly/Def)={qpf_cfg.get('prob_chance_in', 0.03):.2f}/"
            f"{qpf_cfg.get('prob_likely_in', 0.10):.2f}/"
            f"{qpf_cfg.get('prob_definite_in', 0.25):.2f}"
        )
        self.log(
            "QPF texture: "
            f"window={texture_window}, "
            f"strat<= {texture_strat_max:.2f}, "
            f"conv>= {texture_conv_min:.2f}, "
            f"CAPE tie-break <= {cape_strat_max:.0f} / >= {cape_conv_min:.0f} J/kg"
        )
        self.log(
            "Ice accretion: "
            f"SST>{ice_sst_min_f:.0f}F, "
            f"light>={ice_light_min:.2f}, "
            f"moderate>={ice_moderate_min:.2f}, "
            f"heavy>={ice_heavy_min:.2f}, "
            f"max={ice_max:.2f}, "
            f"Wx={ice_cov}:{ice_type}, "
            f"area={ice_area_name or 'None'}"
        )
        self.log(f"Snow QPF scale: {SNOW_QPF_SCALE:.2f}x")

        # Get forecast grid times
        gridinfos = self.getGridInfo("Fcst", "Wx", "SFC", timeRange)
        if not gridinfos:
            self.statusBarMsg("No Wx grids found", "S")
            return

        periods_processed = 0
        total_periods = len(gridinfos)

        # Build edit-area mask once (same grid shape as Fcst Wx/Wind)
        edit_mask = None
        try:
            ea = editArea if editArea is not None else self.getActiveEditArea()
            if ea is None:
                edit_mask = None
            elif hasattr(ea, "isEmpty") and ea.isEmpty():
                # Empty edit area in GFE usually means "all points"
                edit_mask = None
            else:
                edit_mask = ea.getGrid().getNDArray().astype(bool)
        except Exception:
            edit_mask = None

        # Ice accretion area mask (e.g., OPC_AOR) to avoid inland lakes
        ice_area_mask = None
        if ice_area_name:
            try:
                ice_area = self.getEditArea(ice_area_name)
                if ice_area is not None:
                    ice_area_mask = ice_area.getGrid().getNDArray().astype(bool)
                else:
                    ice_area_mask = None
            except Exception:
                try:
                    ice_area = self.getEditArea(ice_area_name)
                    ice_area_mask = self.encodeEditArea(ice_area) if ice_area is not None else None
                except Exception:
                    ice_area_mask = None
            if ice_area_mask is None:
                self.log(f"⚠ Ice accretion edit area '{ice_area_name}' not available; no mask applied")

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total_periods}", "R")
            self.log(f"\nPeriod {i+1}/{total_periods}: {grid_tr}")
            # Per-model data availability/logging is emitted inside _get_ensemble_data

            # Get model data
            model_data = self._get_ensemble_data(models, grid_tr, run_depth, create_diag=create_diag)
            if model_data is None:
                continue

            temp_c, rh, qpf_in, vis_nm, cape = model_data
            qpf_raw = np.array(qpf_in, copy=True) if qpf_in is not None else None

            # Get forecast wind (in knots)
            wind = self.getGrids("Fcst", "Wind", "SFC", grid_tr, mode="First", noDataError=0)
            # Get forecast SST (in F) for ice accretion
            sst_f = self.getGrids("Fcst", "SST", "SFC", grid_tr, mode="First", noDataError=0)

            # Apply smoothing (QPF texture is computed from unsmoothed QPF)
            if smoothing > 0:
                sigma = smoothing * sigma_base
                if qpf_in is not None:
                    qpf_in = ndimage.gaussian_filter(qpf_in, sigma=sigma, mode="nearest")
                if vis_nm is not None:
                    vis_nm = ndimage.gaussian_filter(vis_nm, sigma=sigma, mode="nearest")

            qpf_texture = None
            if qpf_raw is not None:
                try:
                    qpf_texture, _ = _compute_qpf_texture(qpf_raw, texture_window, texture_eps)
                except Exception:
                    qpf_texture = None

            ice_ppr = None
            ice_mask = None
            ice_light_mask = None
            ice_moderate_mask = None
            ice_heavy_mask = None
            if sst_f is not None and temp_c is not None and wind is not None:
                try:
                    ice_ppr = _compute_ice_accretion(temp_c, sst_f, wind[0], ice_cfg)
                    ice_ppr = np.maximum(ice_ppr, 0.0)
                except Exception:
                    ice_ppr = None

                if ice_ppr is not None:
                    valid_mask = sst_f > ice_sst_min_f
                    if ice_area_mask is not None:
                        valid_mask &= ice_area_mask
                    if edit_mask is not None:
                        valid_mask &= edit_mask

                    ice_mask = valid_mask & (ice_ppr >= ice_light_min)
                    ice_heavy_mask = ice_mask & (ice_ppr >= ice_heavy_min)
                    ice_moderate_mask = ice_mask & ~ice_heavy_mask & (ice_ppr >= ice_moderate_min)
                    ice_light_mask = ice_mask & ~(ice_heavy_mask | ice_moderate_mask)

                    if create_ice_grid:
                        try:
                            ice_grid = self.getGrids(
                                "Fcst", "IceAccretion", "SFC", grid_tr, mode="First", noDataError=0
                            )
                        except Exception:
                            ice_grid = None

                        if ice_grid is None:
                            ice_out = np.zeros_like(ice_ppr)
                        else:
                            ice_out = np.array(ice_grid, copy=True)

                        if np.any(valid_mask):
                            ice_out[valid_mask] = np.minimum(ice_ppr[valid_mask], ice_max)
                        ice_out = np.clip(ice_out, 0.0, ice_max)
                        try:
                            self.createGrid(
                                "Fcst",
                                "IceAccretion",
                                "SCALAR",
                                ice_out,
                                grid_tr,
                                minAllowedValue=0.0,
                                maxAllowedValue=ice_max,
                            )
                        except Exception as e:
                            self.log(f"✗ Error saving IceAccretion grid: {e}")

            # Create diagnostic grids
            if create_diag:
                self._create_diagnostics(
                    grid_tr,
                    temp_c,
                    rh,
                    qpf_in,
                    vis_nm,
                    cape,
                    wind,
                    diag_clip,
                    conv_idx_thresh,
                )

            # Determine weather conditions
            qpf_detect = qpf_raw if qpf_raw is not None else qpf_in
            has_precip = qpf_detect > precip_min if qpf_detect is not None else None
            has_thunder = (
                (cape > cape_cfg.get("thunder_min", thunder_thresh)) & (qpf_detect > precip_min)
                if (cape is not None and qpf_detect is not None)
                else None
            )
            has_fog = (vis_nm < fog_thresh) & (rh > fog_rh_min) if vis_nm is not None and rh is not None else None

            # If fog is present, lower the Fcst Visibility grid accordingly (in NM)
            if copy_fog_visibility and has_fog is not None and np.any(has_fog):
                try:
                    vis_fcst = self.getGrids("Fcst", "Visibility", "SFC", grid_tr, mode="First", noDataError=0)
                    if vis_fcst is not None:
                        vis_fcst_out = np.copy(vis_fcst)
                        if edit_mask is not None:
                            fog_points = has_fog & edit_mask
                        else:
                            fog_points = has_fog
                        if np.any(fog_points):
                            vis_fcst_out[fog_points] = np.minimum(vis_fcst_out[fog_points], fog_thresh)
                        self.createGrid("Fcst", "Visibility", "SCALAR", vis_fcst_out, grid_tr)
                except Exception:
                    # Non-fatal; continue building Wx
                    pass

            # Get existing Wx grid
            wx_grid = self.getGrids("Fcst", "Wx", "SFC", grid_tr, noDataError=0)
            if wx_grid is None:
                continue

            wx_values, keys = wx_grid
            # Use int16 to avoid overflow if key index > 127
            updated_wx = np.array(wx_values, dtype=np.int16, copy=True)
            no_wx = "<NoCov>:<NoWx>:<NoInten>:<NoVis>:"
            no_idx = self.getIndex(no_wx, keys)

            # Scope output to edit area; outside editArea remains unchanged
            if edit_mask is not None:
                active = edit_mask
            else:
                active = None

            # Build mode baseline inside the active area
            if build_mode.startswith("Build New"):
                if active is None:
                    updated_wx[:, :] = no_idx
                else:
                    updated_wx[active] = no_idx

            # Cache indices for the small set of Wx strings we emit
            idx_cache = {no_wx: no_idx}

            def _idx(wx_str: str) -> int:
                val = idx_cache.get(wx_str)
                if val is not None:
                    return val
                idx_cache[wx_str] = self.getIndex(wx_str, keys)
                return idx_cache[wx_str]

            def _safe_idx(wx_str: str) -> Optional[int]:
                try:
                    return _idx(wx_str)
                except Exception:
                    return None

            def _combine_wx(existing: str, addition: str) -> str:
                if existing == no_wx:
                    return addition
                parts = existing.split("^")
                if addition in parts:
                    return existing
                return "^".join(parts + [addition])

            def _normalize_wx_string(wx_str: str) -> str:
                components = wx_str.split("^")
                normalized = []
                for comp in components:
                    comp = comp.rstrip(":")
                    fields = comp.split(":")
                    if len(fields) > 4:
                        fields = fields[:4]
                    while len(fields) < 4:
                        fields.append("<NoVis>")
                    normalized.append(":".join(fields) + ":")
                return "^".join(normalized)

            def _append_wx(mask: np.ndarray, addition: str):
                if not np.any(mask):
                    return
                add_idx = _safe_idx(addition)
                if add_idx is None:
                    return
                no_mask = mask & (updated_wx == no_idx)
                if np.any(no_mask):
                    updated_wx[no_mask] = add_idx
                combo_mask = mask & (updated_wx != no_idx)
                if not np.any(combo_mask):
                    return
                existing_vals = np.unique(updated_wx[combo_mask])
                for ex_idx in existing_vals:
                    if ex_idx == no_idx:
                        continue
                    ex_str = keys[ex_idx]
                    combined = _normalize_wx_string(_combine_wx(ex_str, addition))
                    combined_idx = _safe_idx(combined)
                    if combined_idx is None:
                        continue
                    updated_wx[(updated_wx == ex_idx) & combo_mask] = combined_idx

            def _pick_ice_wx(inten: str) -> Optional[str]:
                coverages = [ice_cov, "Sct", "Num", "Wide", "Areas", "Iso", "Patchy"]
                types = [ice_type, "ZY", "FZSPR", "ZR"]
                for cov in coverages:
                    for typ in types:
                        candidate = f"{cov}:{typ}:{inten}:<NoVis>:"
                        if _safe_idx(candidate) is not None:
                            return candidate
                        if inten != "<NoInten>":
                            fallback = f"{cov}:{typ}:<NoInten>:<NoVis>:"
                            if _safe_idx(fallback) is not None:
                                return fallback
                # Final fallback: pick any existing key with matching type/intensity
                for key in keys:
                    parts = key.rstrip(":").split(":")
                    if len(parts) < 4:
                        continue
                    _, wx_type, wx_inten, _ = parts[:4]
                    if wx_type in {"FZSPR", "ZR", ice_type} and wx_inten == inten:
                        return ":".join(parts[:4]) + ":"
                if inten != "<NoInten>":
                    for key in keys:
                        parts = key.rstrip(":").split(":")
                        if len(parts) < 4:
                            continue
                        _, wx_type, wx_inten, _ = parts[:4]
                        if wx_type in {"FZSPR", "ZR", ice_type} and wx_inten == "<NoInten>":
                            return ":".join(parts[:4]) + ":"
                return None

            # Build masks for decisioning
            if has_thunder is not None:
                thunder_mask = has_thunder.copy()
            else:
                thunder_mask = np.zeros(wx_values.shape, dtype=bool)

            if has_precip is not None:
                precip_mask = has_precip.copy()
            else:
                precip_mask = np.zeros(wx_values.shape, dtype=bool)

            if has_fog is not None:
                fog_mask = has_fog.copy()
            else:
                fog_mask = np.zeros(wx_values.shape, dtype=bool)

            if active is not None:
                thunder_mask &= active
                precip_mask &= active
                fog_mask &= active

            # Precedence: thunder > precip > fog
            precip_mask &= ~thunder_mask
            fog_mask &= ~(thunder_mask | precip_mask)

            # --- Fog assignment
            if np.any(fog_mask):
                updated_wx[fog_mask] = _idx("Patchy:F:<NoInten>:<NoVis>:")

            # --- Thunder assignment
            if np.any(thunder_mask) and cape is not None:
                cape_val = cape
                cape_high = float(cape_cfg.get("high", 2000.0))
                cape_severe = float(cape_cfg.get("severe_min", 3000.0))
                severe_with_qpf = float(qpf_cfg.get("severe_with_thunder_in", 1.0))

                cov_sct = thunder_mask & (cape_val > cape_high)
                cov_iso = thunder_mask & ~cov_sct

                severe = thunder_mask & (cape_val > cape_severe)
                if qpf_in is not None:
                    severe |= thunder_mask & (qpf_in > severe_with_qpf)

                # Note: Wx encoding uses '+' intensity for severe; otherwise <NoInten>
                if np.any(cov_sct & severe):
                    updated_wx[cov_sct & severe] = _idx("Sct:T:+:<NoVis>:")
                if np.any(cov_sct & ~severe):
                    updated_wx[cov_sct & ~severe] = _idx("Sct:T:<NoInten>:<NoVis>:")
                if np.any(cov_iso & severe):
                    updated_wx[cov_iso & severe] = _idx("Iso:T:+:<NoVis>:")
                if np.any(cov_iso & ~severe):
                    updated_wx[cov_iso & ~severe] = _idx("Iso:T:<NoInten>:<NoVis>:")

            # --- Precip assignment (rain/snow + convective coverage/prob + intensity)
            if np.any(precip_mask) and qpf_in is not None:
                # Convective vs stratiform using QPF texture + CAPE
                if qpf_texture is not None:
                    is_conv = qpf_texture >= texture_conv_min
                    is_conv = np.where(qpf_texture <= texture_strat_max, False, is_conv)
                    if cape is not None:
                        is_conv = np.where(cape <= cape_strat_max, False, is_conv)
                        is_conv = np.where(cape >= cape_conv_min, True, is_conv)
                else:
                    if cape is not None:
                        is_conv = cape >= cape_conv_min
                    else:
                        is_conv = np.zeros(wx_values.shape, dtype=bool)

                # Precip type by temperature (Celsius)
                if temp_c is not None:
                    is_snow = temp_c < FREEZING_C
                else:
                    is_snow = np.zeros(wx_values.shape, dtype=bool)

                if SNOW_QPF_SCALE != 1.0:
                    qpf_eff = np.where(is_snow, qpf_in * SNOW_QPF_SCALE, qpf_in)
                else:
                    qpf_eff = qpf_in

                # Thresholds
                precip_wide = float(qpf_cfg.get("coverage_wide_in", 0.25))
                precip_numerous = float(qpf_cfg.get("coverage_numerous_in", 0.10))
                precip_scattered = float(qpf_cfg.get("coverage_scattered_in", 0.03))
                precip_definite = float(qpf_cfg.get("prob_definite_in", 0.25))
                precip_likely = float(qpf_cfg.get("prob_likely_in", 0.10))
                precip_chance = float(qpf_cfg.get("prob_chance_in", 0.03))
                precip_heavy = float(qpf_cfg.get("heavy_in", 0.50))
                precip_moderate = float(qpf_cfg.get("moderate_in", 0.25))
                precip_light = float(qpf_cfg.get("light_in", 0.05))

                # Intensity masks
                inten_plus = precip_mask & (qpf_eff > precip_heavy)
                inten_m = precip_mask & ~inten_plus & (qpf_eff > precip_moderate)
                inten_minus = precip_mask & ~(inten_plus | inten_m)  # keep '-' as default

                # Coverage/probability masks
                conv_points = precip_mask & is_conv
                strat_points = precip_mask & ~is_conv

                cov_wide = conv_points & (qpf_eff > precip_wide)
                cov_num = conv_points & ~cov_wide & (qpf_eff > precip_numerous)
                cov_sct = conv_points & ~(cov_wide | cov_num) & (qpf_eff > precip_scattered)
                cov_iso = conv_points & ~(cov_wide | cov_num | cov_sct)

                cov_def = strat_points & (qpf_eff > precip_definite)
                cov_lkly = strat_points & ~cov_def & (qpf_eff > precip_likely)
                cov_chc = strat_points & ~(cov_def | cov_lkly) & (qpf_eff > precip_chance)
                cov_schc = strat_points & ~(cov_def | cov_lkly | cov_chc)

                # Pre-build Wx strings with fixed fields
                # Format: "<Cov>:<WxType>:<Inten>:<NoVis>:"
                def wx(cov, typ, inten):
                    return f"{cov}:{typ}:{inten}:<NoVis>:"

                def assign_cov(cov_mask, cov_code, convective: bool):
                    # Determine precip weather type string per-point (snow/rain + convective flag)
                    if convective:
                        rain_type = "RW"
                        snow_type = "SW"
                    else:
                        rain_type = "R"
                        snow_type = "S"

                    snow_mask = cov_mask & is_snow
                    rain_mask = cov_mask & ~is_snow

                    if np.any(rain_mask & inten_plus):
                        updated_wx[rain_mask & inten_plus] = _idx(wx(cov_code, rain_type, "+"))
                    if np.any(rain_mask & inten_m):
                        updated_wx[rain_mask & inten_m] = _idx(wx(cov_code, rain_type, "m"))
                    if np.any(rain_mask & inten_minus):
                        updated_wx[rain_mask & inten_minus] = _idx(wx(cov_code, rain_type, "-"))

                    if np.any(snow_mask & inten_plus):
                        updated_wx[snow_mask & inten_plus] = _idx(wx(cov_code, snow_type, "+"))
                    if np.any(snow_mask & inten_m):
                        updated_wx[snow_mask & inten_m] = _idx(wx(cov_code, snow_type, "m"))
                    if np.any(snow_mask & inten_minus):
                        updated_wx[snow_mask & inten_minus] = _idx(wx(cov_code, snow_type, "-"))

                # Convective coverage
                assign_cov(cov_wide, "Wide", convective=True)
                assign_cov(cov_num, "Num", convective=True)
                assign_cov(cov_sct, "Sct", convective=True)
                assign_cov(cov_iso, "Iso", convective=True)

                # Stratiform probability
                assign_cov(cov_def, "Def", convective=False)
                assign_cov(cov_lkly, "Lkly", convective=False)
                assign_cov(cov_chc, "Chc", convective=False)
                assign_cov(cov_schc, "SChc", convective=False)

            # --- Ice accretion (freezing spray)
            if ice_mask is not None and np.any(ice_mask):
                ice_wx_light = _pick_ice_wx("-")
                ice_wx_moderate = _pick_ice_wx("m")
                ice_wx_heavy = _pick_ice_wx("+")

                if not any([ice_wx_light, ice_wx_moderate, ice_wx_heavy]):
                    self.log("⚠ No valid Wx key found for ice accretion; skipping Wx add")

                if ice_light_mask is not None and np.any(ice_light_mask) and ice_wx_light:
                    _append_wx(ice_light_mask, ice_wx_light)
                if ice_moderate_mask is not None and np.any(ice_moderate_mask) and ice_wx_moderate:
                    _append_wx(ice_moderate_mask, ice_wx_moderate)
                if ice_heavy_mask is not None and np.any(ice_heavy_mask) and ice_wx_heavy:
                    _append_wx(ice_heavy_mask, ice_wx_heavy)

            # Save weather grid
            try:
                self.createGrid("Fcst", "Wx", "WEATHER", (updated_wx, keys), grid_tr)
                periods_processed += 1
                self.log(f"✓ Weather grid saved")
            except Exception as e:
                self.log(f"✗ Error saving grid: {e}")

        self.log("\n" + "="*80)
        self.log(f"Complete: {periods_processed}/{total_periods} periods")
        self.statusBarMsg(f"Complete: {periods_processed} periods", "R")
        
        # Show results popup after execution
        self._show_results_popup()

    def _show_gui(self) -> Optional[Dict]:
        root = tk.Tk()
        result = [None]

        def callback(values):
            result[0] = values

        gui = MarineWeatherGUI(root, callback)
        root.mainloop()
        return result[0]

    def _get_ensemble_data(self, models: List[str], grid_tr, run_depth: int, *, create_diag: bool = False):
        """Get averaged model data using alias configuration."""
        temp_sum, rh_sum, qpf_sum, vis_min, cape_max = None, None, None, None, None
        temp_cnt, rh_cnt, qpf_cnt = 0, 0, 0
        # Log which model_aliases module is actually imported (placed with per-period logging)

        def _cand_list(*vals):
            """Return list of unique, truthy candidates preserving order."""
            seen = set()
            out = []
            for v in vals:
                if not v:
                    continue
                if v in seen:
                    continue
                seen.add(v)
                out.append(v)
            return out

        per_model_reports = []

        for alias in models:
            try:
                cfg = model_aliases.get_model_config(alias)
            except KeyError:
                self.log(f"✗ Unknown model alias {alias}")
                continue

            def _to_f_and_c(raw):
                """Convert raw model temperature to (F, C) with a robust unit guess."""
                candidates = []

                def add(label, fgrid):
                    med = np.nanmedian(fgrid)
                    maxv = np.nanmax(fgrid)
                    candidates.append((label, fgrid, med, maxv))

                # Candidate: Kelvin -> F
                add("K", (raw - 273.15) * 9.0 / 5.0 + 32.0)
                # Candidate: Fahrenheit (as-is)
                add("F", raw)
                # Candidate: Celsius -> F
                add("C", raw * 9.0 / 5.0 + 32.0)

                def score(cand):
                    _, _, med, maxv = cand
                    # Prefer realistic medians and maxima in plausible weather range
                    if med < -150 or med > 180 or maxv > 200:
                        return 1e9 + abs(med)
                    return abs(med - 60.0)

                chosen = min(candidates, key=score)
                temp_f = chosen[1]
                temp_c = (temp_f - 32.0) * (5.0 / 9.0)
                return temp_f, temp_c

            # Build candidates using registry defaults and legacy names
            temp_levels = _cand_list(
                cfg.default_levels.get("temp"),
                cfg.default_levels.get("rh"),  # often aligned
                "MB1000",
                "SFC",
            )
            rh_levels = _cand_list(cfg.default_levels.get("rh"), cfg.default_levels.get("temp"), "MB1000", "SFC")
            qpf_levels = _cand_list(cfg.default_levels.get("qpf"), "0.0SFC", "SFC")
            vis_levels = _cand_list(cfg.default_levels.get("vis"), "SFC", "0.0SFC")
            cape_levels = _cand_list(cfg.default_levels.get("cape"), "SFC", "0.0SFC")

            temp_elems = _cand_list(cfg.parameter_overrides.get("Temperature"), "T", "t")
            rh_elems = _cand_list(cfg.parameter_overrides.get("RH"), "RH", "rh")
            vis_elems = _cand_list(
                cfg.parameter_overrides.get("Visibility"),
                "Vsby",
                "vsby",
                "vis",
                "VIS",
                "VSBY",
            )
            qpf_elems = _cand_list(
                cfg.parameter_overrides.get("QPF"),
                "TP3hr",
                "tp",
                "QPF",
                "APCP",
                "apcp",
            )
            cape_elems = _cand_list(
                cfg.parameter_overrides.get("CAPE"),
                "SBCAPE",
                "cape",
                "CAPE",
                "MLCAPE",
                "mlcape",
            )

            # Temperature
            temp = grid_fetch.get_grid_with_fallback(
                self, alias, temp_elems, temp_levels, grid_tr, run_depth=run_depth, noDataError=0
            )
            if temp is not None:
                temp_f, temp_c = _to_f_and_c(temp)
                temp_sum = temp_c if temp_sum is None else temp_sum + temp_c
                temp_cnt += 1

            rh_stats = None
            temp_stats = None
            qpf_stats = None
            vis_stats = None
            cape_stats = None

            # RH
            rh = grid_fetch.get_grid_with_fallback(
                self, alias, rh_elems, rh_levels, grid_tr, run_depth=run_depth, noDataError=0
            )
            if rh is not None:
                rh_sum = rh if rh_sum is None else rh_sum + rh
                rh_cnt += 1
                rh_stats = (float(np.nanmin(rh)), float(np.nanmean(rh)), float(np.nanmax(rh)))

            # QPF - log what we're trying
            if alias in ["ECMWF", "CMC"]:
                self.log(f"  {alias} QPF: trying elements {qpf_elems} at levels {qpf_levels}")
            qpf = grid_fetch.get_grid_with_fallback(
                self, alias, qpf_elems, qpf_levels, grid_tr, run_depth=run_depth, noDataError=0
            )
            if qpf is not None:
                try:
                    qpf_in = thresholds.mm_to_inches(qpf)
                except AttributeError:
                    qpf_in = qpf / 25.4
                qpf_sum = qpf_in if qpf_sum is None else qpf_sum + qpf_in
                qpf_cnt += 1
                qpf_stats = (float(np.nanmin(qpf_in)), float(np.nanmean(qpf_in)), float(np.nanmax(qpf_in)))

                if create_diag:
                    # Per-model diagnostic QPF (inches), clipped to 0-1 for display
                    try:
                        qpf_clip = np.clip(qpf_in, 0.0, 1.0)
                        elem_name = f"modelQPF{alias.upper()}"
                        self.createGrid(
                            "Fcst",
                            elem_name,
                            "SCALAR",
                            qpf_clip,
                            grid_tr,
                            minAllowedValue=0.0,
                            maxAllowedValue=1.0,
                            units="in",
                            descriptiveName=f"{alias} QPF (in)",
                        )
                    except Exception:
                        pass

            # Visibility - log what we're trying
            if alias in ["ECMWF", "CMC"]:
                self.log(f"  {alias} Vis: trying elements {vis_elems} at levels {vis_levels}")
            vis = grid_fetch.get_grid_with_fallback(
                self, alias, vis_elems, vis_levels, grid_tr, run_depth=run_depth, noDataError=0
            )
            if vis is not None:
                try:
                    vis_nm = thresholds.meters_to_nm(vis)
                except AttributeError:
                    vis_nm = vis / 1852.0
                vis_min = vis_nm if vis_min is None else np.minimum(vis_min, vis_nm)
                vis_stats = (float(np.nanmin(vis_nm)), float(np.nanmean(vis_nm)), float(np.nanmax(vis_nm)))

            # CAPE - log what we're trying
            if alias in ["ECMWF", "CMC"]:
                self.log(f"  {alias} CAPE: trying elements {cape_elems} at levels {cape_levels}")
            cape = grid_fetch.get_grid_with_fallback(
                self, alias, cape_elems, cape_levels, grid_tr, run_depth=run_depth, noDataError=0
            )
            if cape is not None:
                cape_max = cape if cape_max is None else np.maximum(cape_max, cape)
                cape_stats = (float(np.nanmin(cape)), float(np.nanmean(cape)), float(np.nanmax(cape)))

            if temp is not None:
                temp_stats = (float(np.nanmin(temp_c)), float(np.nanmean(temp_c)), float(np.nanmax(temp_c)))

            # Summarize per-model availability for this time
            parts = [f"{alias}: "]
            parts.append(f"T {temp_stats[0]:.1f}/{temp_stats[1]:.1f}/{temp_stats[2]:.1f} C" if temp_stats else "T missing")
            parts.append(f"RH {rh_stats[0]:.0f}/{rh_stats[1]:.0f}/{rh_stats[2]:.0f}%" if rh_stats else "RH missing")
            parts.append(f"QPF {qpf_stats[0]:.2f}/{qpf_stats[1]:.2f}/{qpf_stats[2]:.2f}\"" if qpf_stats else "QPF missing")
            parts.append(f"Vsby {vis_stats[0]:.2f}/{vis_stats[1]:.2f}/{vis_stats[2]:.2f} nm" if vis_stats else "Vsby missing")
            parts.append(f"CAPE {cape_stats[0]:.0f}/{cape_stats[1]:.0f}/{cape_stats[2]:.0f} J/kg" if cape_stats else "CAPE missing")
            per_model_reports.append(" | ".join(parts))

        if temp_cnt == 0 and qpf_cnt == 0:
            self.log(f"  No temp or QPF available for aliases {models}; skipping period")
            return None

        # Log per-model stats for this time slice
        for line in per_model_reports:
            self.log(f"  {line}")
            # Also surface to status bar for operator visibility
            try:
                self.statusBarMsg(line, "R")
            except Exception:
                pass

        temp_avg = temp_sum / temp_cnt if temp_cnt > 0 else None
        rh_avg = rh_sum / rh_cnt if rh_cnt > 0 else None
        qpf_avg = qpf_sum / qpf_cnt if qpf_cnt > 0 else None

        return temp_avg, rh_avg, qpf_avg, vis_min, cape_max

    def _create_diagnostics(self, grid_tr, temp_c, rh, qpf_in, vis_nm, cape, wind, clip, conv_idx_thresh):
        """Create diagnostic grids."""
        # Use fixed, predictable ranges for diagnostics to ensure display limits stick
        qpf_max = 1.0
        cape_max = 5000.0
        temp_min_f, temp_max_f = -50.0, 130.0
        rh_min, rh_max = 0.0, 100.0
        vis_min, vis_max = 0.0, 10.0
        conv_clip_min, conv_clip_max = 0.0, 10.0

        if qpf_in is not None:
            qpf_clipped = np.clip(qpf_in, 0, qpf_max)
            self.createGrid(
                "Fcst",
                "modelQPF",
                "SCALAR",
                qpf_clipped,
                grid_tr,
                minAllowedValue=0.0,
                maxAllowedValue=qpf_max,
            )

        if cape is not None:
            cape_clipped = np.clip(cape, 0, cape_max)
            self.createGrid(
                "Fcst",
                "modelCAPE",
                "SCALAR",
                cape_clipped,
                grid_tr,
                minAllowedValue=0.0,
                maxAllowedValue=cape_max,
            )

        if temp_c is not None:
            try:
                temp_f = thresholds.c_to_f(temp_c)
            except AttributeError:
                # Fallback: C to F conversion (F = C * 9/5 + 32)
                temp_f = temp_c * 9.0/5.0 + 32.0
            temp_f_clipped = np.clip(temp_f, temp_min_f, temp_max_f)
            self.createGrid(
                "Fcst",
                "modelT",
                "SCALAR",
                temp_f_clipped,
                grid_tr,
                minAllowedValue=temp_min_f,
                maxAllowedValue=temp_max_f,
                units="F",
            )

        if rh is not None:
            rh_clipped = np.clip(rh, rh_min, rh_max)
            self.createGrid(
                "Fcst",
                "modelRH",
                "SCALAR",
                rh_clipped,
                grid_tr,
                minAllowedValue=rh_min,
                maxAllowedValue=rh_max,
            )

        if vis_nm is not None:
            vis_clipped = np.clip(vis_nm, vis_min, vis_max)
            self.createGrid(
                "Fcst",
                "modelVsby",
                "SCALAR",
                vis_clipped,
                grid_tr,
                minAllowedValue=vis_min,
                maxAllowedValue=vis_max,
            )

        if cape is not None and wind is not None:
            # Fcst Wind is (magnitude_knots, direction_degrees)
            wind_speed_kt = wind[0]
            try:
                wind_speed_ms = thresholds.to_mps(wind_speed_kt)
            except AttributeError:
                wind_speed_ms = wind_speed_kt * 0.514444
            conv_index = (cape / 1000.0) + (wind_speed_ms / 20.0)
            conv_index_clipped = np.clip(conv_index, conv_clip_min, conv_clip_max)
            self.createGrid(
                "Fcst",
                "modelConvectiveIndex",
                "SCALAR",
                conv_index_clipped,
                grid_tr,
                minAllowedValue=conv_clip_min,
                maxAllowedValue=conv_clip_max,
            )

    def _determine_weather(
        self,
        ii,
        jj,
        has_precip,
        has_thunder,
        has_fog,
        qpf,
        cape,
        temp_c,
        wind,
        qpf_cfg,
        conv_idx_thresh,
        cape_cfg,
    ):
        """Determine weather string for a grid point."""
        # Thunder
        if has_thunder is not None and has_thunder[ii, jj]:
            cape_val = cape[ii, jj] if cape is not None else 0.0
            cape_high = cape_cfg.get("high", 2000.0)
            cape_severe = cape_cfg.get("severe_min", 3000.0)
            if cape_val > cape_high:
                cov = "Sct"
            else:
                cov = "Iso"

            is_severe = cape_val > cape_severe
            if qpf is not None and qpf_cfg:
                if qpf[ii, jj] > qpf_cfg.get("severe_with_thunder_in", 1.0):
                    is_severe = True
            intensity = "+" if is_severe else "<NoInten>"
            return f"{cov}:T:{intensity}:<NoVis>:"

        # Precipitation
        if has_precip is not None and has_precip[ii, jj]:
            if qpf is None:
                return None
            qpf_val = qpf[ii, jj]
            cape_val = cape[ii, jj] if cape is not None else 0

            # Get wind speed in m/s for convective index
            wind_ms = 0
            if wind is not None:
                # Fcst Wind is (magnitude_knots, direction_degrees)
                wind_kt = wind[0][ii, jj]
                try:
                    wind_ms = thresholds.to_mps(wind_kt)
                except AttributeError:
                    # Fallback: knots to m/s (1 kt = 0.514444 m/s)
                    wind_ms = wind_kt * 0.514444

            conv_idx = (cape_val / 1000.0) + (wind_ms / 20.0)
            is_conv = conv_idx > conv_idx_thresh

            precip_wide = qpf_cfg.get("coverage_wide_in", 0.25)
            precip_numerous = qpf_cfg.get("coverage_numerous_in", 0.10)
            precip_scattered = qpf_cfg.get("coverage_scattered_in", 0.03)
            precip_definite = qpf_cfg.get("prob_definite_in", 0.25)
            precip_likely = qpf_cfg.get("prob_likely_in", 0.10)
            precip_chance = qpf_cfg.get("prob_chance_in", 0.03)
            precip_heavy = qpf_cfg.get("heavy_in", 0.50)
            precip_moderate = qpf_cfg.get("moderate_in", 0.25)
            precip_light = qpf_cfg.get("light_in", 0.05)
            
            if is_conv:
                if qpf_val > precip_wide:
                    cov = "Wide"
                elif qpf_val > precip_numerous:
                    cov = "Num"
                elif qpf_val > precip_scattered:
                    cov = "Sct"
                else:
                    cov = "Iso"
            else:
                if qpf_val > precip_definite:
                    cov = "Def"
                elif qpf_val > precip_likely:
                    cov = "Lkly"
                elif qpf_val > precip_chance:
                    cov = "Chc"
                else:
                    cov = "SChc"

            # Intensity
            if qpf_val > precip_heavy:
                intensity = "+"
            elif qpf_val > precip_moderate:
                intensity = "m"
            elif qpf_val > precip_light:
                intensity = "-"
            else:
                intensity = "-"

            # Type (rain vs snow) - freezing point is 32°F
            if temp_c is not None and temp_c[ii, jj] < FREEZING_C:
                wx_type = "SW" if is_conv else "S"
            else:
                wx_type = "RW" if is_conv else "R"

            return f"{cov}:{wx_type}:{intensity}:<NoVis>:"

        # Fog
        if has_fog is not None and has_fog[ii, jj]:
            return "Patchy:F:<NoInten>:<NoVis>:"

        return None


__all__ = ["Procedure"]

