"""
Marine Weather Grid Builder - Comprehensive Wx grid creation tool.

Builds weather grids from atmospheric model data including precipitation,
thunderstorms, and fog. Uses shared utilities for model access.

Features:
    - Multi-model ensemble support (GFS, ECMWF, CMC, UKMET)
    - Automatic qualifier determination (convective vs stratiform)
    - GUI-adjustable QPF thresholds for coverage and probability
    - Spatial smoothing and configurable thresholds
    - Diagnostic grid output (QPF, CAPE, Temperature, RH, Visibility)
    - Optional Fcst Visibility grid updates for fog detection

Data Structures:
    - Wind grids from Fcst database are tuples: (magnitude_knots, direction_degrees)
      where wind[0] is the magnitude array in knots and wind[1] is direction in degrees
    - Temperature is processed in Celsius internally, converted from K or F as needed
    - QPF is processed in inches, converted from mm as needed
    - Visibility is processed in nautical miles, converted from meters as needed

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


# ---------------------------------------------------------------------------
# Thermodynamic calculation functions
# ---------------------------------------------------------------------------

def compute_dewpoint_c(temp_c: np.ndarray, rh_pct: np.ndarray) -> np.ndarray:
    """
    Compute dew point temperature from temperature and relative humidity.
    
    Uses the Magnus-Tetens approximation:
    Td = (b * alpha) / (a - alpha)
    where alpha = (a * T) / (b + T) + ln(RH/100)
    
    Args:
        temp_c: Temperature in Celsius
        rh_pct: Relative humidity in percent (0-100)
        
    Returns:
        Dew point temperature in Celsius
    """
    # Magnus-Tetens constants
    a = 17.27
    b = 237.7  # degrees C
    
    # Clamp RH to avoid log(0)
    rh_safe = np.clip(rh_pct, 0.1, 100.0)
    
    alpha = (a * temp_c) / (b + temp_c) + np.log(rh_safe / 100.0)
    td = (b * alpha) / (a - alpha)
    
    return td


def compute_lcl_temp_c(temp_c: np.ndarray, td_c: np.ndarray) -> np.ndarray:
    """
    Compute Lifting Condensation Level (LCL) temperature.
    
    Uses Espy's equation approximation:
    T_LCL ≈ Td - (0.125 * (T - Td))
    
    More accurate formula:
    T_LCL = 1 / (1/(Td - 56) + ln(T/Td)/800) + 56
    
    Args:
        temp_c: Surface temperature in Celsius
        td_c: Surface dew point in Celsius
        
    Returns:
        LCL temperature in Celsius
    """
    # Use Bolton's formula for better accuracy
    # Avoid division by zero
    td_safe = np.where(td_c < -55, -55, td_c)
    t_safe = np.where(temp_c < td_safe, td_safe + 0.1, temp_c)
    
    term1 = 1.0 / (td_safe - 56.0 + 1e-10)
    term2 = np.log(t_safe / (td_safe + 1e-10)) / 800.0
    
    t_lcl = 1.0 / (term1 + term2 + 1e-10) + 56.0
    
    return t_lcl


def compute_lifted_index(temp_sfc_c: np.ndarray, td_sfc_c: np.ndarray, 
                          temp_500_c: np.ndarray) -> np.ndarray:
    """
    Compute Lifted Index (LI).
    
    LI = T500_env - T500_parcel
    
    Simplified calculation that lifts a parcel from the surface to 500mb.
    Negative values indicate instability.
    
    Args:
        temp_sfc_c: Surface temperature in Celsius
        td_sfc_c: Surface dew point in Celsius
        temp_500_c: 500mb environmental temperature in Celsius
        
    Returns:
        Lifted Index (negative = unstable, positive = stable)
    """
    # Compute LCL temperature
    t_lcl = compute_lcl_temp_c(temp_sfc_c, td_sfc_c)
    
    # Estimate parcel temperature at 500mb
    # Dry adiabatic lapse rate: ~9.8 C/km
    # Moist adiabatic lapse rate: ~6.0 C/km (varies with temperature)
    # Surface to LCL: dry adiabatic
    # LCL to 500mb: moist adiabatic
    
    # Approximate heights: surface ~1000mb, LCL varies, 500mb ~5.5km
    # This is a simplified calculation
    
    # Dry adiabatic cooling to LCL (roughly 1-2 km typically)
    # Then moist adiabatic from LCL to 500mb
    
    # Simplified: use average lapse rate based on moisture
    # Drier air (larger T-Td spread) = more dry adiabatic cooling
    spread = temp_sfc_c - td_sfc_c
    
    # Effective lapse rate (C/km) - interpolate between dry and moist
    # based on moisture (spread)
    dry_rate = 9.8
    moist_rate = 6.0
    # More spread = drier = closer to dry rate
    spread_factor = np.clip(spread / 20.0, 0, 1)  # normalize 0-20C spread
    eff_rate = moist_rate + spread_factor * (dry_rate - moist_rate)
    
    # Approximate lift from surface to 500mb (~5.5 km)
    lift_height_km = 5.5
    
    # Parcel temperature at 500mb
    t_parcel_500 = temp_sfc_c - (eff_rate * lift_height_km)
    
    # Lifted Index
    li = temp_500_c - t_parcel_500
    
    return li


def compute_k_index(temp_850_c: np.ndarray, temp_700_c: np.ndarray, 
                    temp_500_c: np.ndarray, td_850_c: np.ndarray,
                    td_700_c: np.ndarray) -> np.ndarray:
    """
    Compute K-Index for thunderstorm potential.
    
    K = (T850 - T500) + Td850 - (T700 - Td700)
    
    Interpretation:
    - K < 20: No thunderstorm potential
    - K 20-25: Isolated thunderstorms possible
    - K 26-30: Scattered thunderstorms
    - K 31-35: Numerous thunderstorms
    - K > 35: Widespread thunderstorms
    
    Args:
        temp_850_c: 850mb temperature in Celsius
        temp_700_c: 700mb temperature in Celsius
        temp_500_c: 500mb temperature in Celsius
        td_850_c: 850mb dew point in Celsius
        td_700_c: 700mb dew point in Celsius
        
    Returns:
        K-Index value
    """
    k_index = (temp_850_c - temp_500_c) + td_850_c - (temp_700_c - td_700_c)
    return k_index


# ---------------------------------------------------------------------------
# Configuration helpers with safe fallbacks
# ---------------------------------------------------------------------------
# These provide thresholds from the shared module when available, falling back
# to sensible defaults if the thresholds module is incomplete or unavailable.

_DEFAULT_QPF_CFG: Dict[str, float] = {
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
}

_DEFAULT_CONVECTION_CFG: Dict[str, float] = {
    "convective_index_threshold": 2.0,  # Lowered from 7.0 for better convective detection
}

_DEFAULT_FOG_CFG: Dict[str, float] = {
    "visibility_default_nm": 2.6,
    "visibility_min_nm": 0.4,
    "visibility_max_nm": 5.2,
    "relative_humidity_min_pct": 85.0,
}

_DEFAULT_SMOOTHING_CFG: Dict[str, float] = {
    "recommended": 10.0,
    "min": 0.0,
    "max": 20.0,
    "sigma": 0.7,
}

_DEFAULT_CLIP_CFG: Dict[str, float] = {
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

_DEFAULT_CAPE_CFG: Dict[str, float] = {
    "thunder_min": 500.0,
    "severe_min": 3000.0,
    "high": 2000.0,
    "moderate": 1000.0,
}


def _get_threshold_config(getter_name: str, fallback: Dict[str, float]) -> Dict[str, float]:
    """
    Retrieve configuration from thresholds module with fallback.
    
    Args:
        getter_name: Name of the getter function in thresholds module
        fallback: Default dict to return if getter is unavailable
        
    Returns:
        Configuration dictionary from thresholds module or fallback
    """
    try:
        getter = getattr(thresholds, getter_name, None)
        if getter is not None and callable(getter):
            return getter()
    except (AttributeError, TypeError):
        pass
    return fallback.copy()


def _get_safe_qpf_cfg() -> Dict[str, float]:
    """Get QPF thresholds with safe fallback."""
    return _get_threshold_config("get_model_wx_qpf_thresholds", _DEFAULT_QPF_CFG)


def _get_safe_convection_cfg() -> Dict[str, float]:
    """Get convection thresholds with safe fallback."""
    return _get_threshold_config("get_model_wx_convection", _DEFAULT_CONVECTION_CFG)


def _get_safe_fog_cfg() -> Dict[str, float]:
    """Get fog thresholds with safe fallback."""
    return _get_threshold_config("get_model_wx_fog_thresholds_nm", _DEFAULT_FOG_CFG)


def _get_safe_smoothing_cfg() -> Dict[str, float]:
    """Get smoothing parameters with safe fallback."""
    return _get_threshold_config("get_model_wx_smoothing_defaults", _DEFAULT_SMOOTHING_CFG)


def _get_safe_clip_cfg() -> Dict[str, float]:
    """Get diagnostic clipping bounds with safe fallback."""
    return _get_threshold_config("get_diagnostic_clipping", _DEFAULT_CLIP_CFG)


def _get_safe_cape_cfg(thunder_override: float) -> Dict[str, float]:
    """
    Get CAPE thresholds with user override for thunder minimum.
    
    Args:
        thunder_override: User-specified minimum CAPE for thunder detection
        
    Returns:
        CAPE configuration with thunder_min adjusted to user override
    """
    cape_cfg = _get_threshold_config("get_cape_thresholds", _DEFAULT_CAPE_CFG)
    cape_cfg["thunder_min"] = max(thunder_override, cape_cfg.get("thunder_min", thunder_override))
    return cape_cfg


class MarineWeatherGUI:
    """GUI for marine weather grid builder."""

    def __init__(self, master, callback):
        self.master = master
        self.callback = callback
        self.master.title("Marine Weather Grid Builder")
        self.master.geometry("700x900")

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

        # Model Selection
        self._build_model_frame(main)

        # Build Mode
        self._build_mode_frame(main)

        # Parameters
        self._build_params_frame(main)

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

    def _build_params_frame(self, parent):
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

        # Update visibility grid option
        tk.Label(frame, text="Update Visibility Grid for Fog:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(10, 0))
        self.update_vis_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            frame,
            text="Lower Visibility grid where fog is detected",
            variable=self.update_vis_var,
        ).pack(anchor=tk.W)
        tk.Label(
            frame,
            text="When enabled, the Fcst Visibility grid will be lowered to the fog threshold where fog is detected.",
            font=("Arial", 9),
            fg="gray",
            wraplength=420,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 0))

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
            "update_vis_for_fog": self.update_vis_var.get(),
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
        """
        Show results popup with all log output after execution.
        
        Creates a Tk window to display execution results. Handles both cases
        where a Tk root already exists (AWIPS environment) and standalone mode.
        """
        output_text = "\n".join(self.output_log) if self.output_log else "No output generated."
        
        # Try to find existing Tk root, create one if needed
        parent = getattr(tk, "_default_root", None)
        owns_root = False
        
        try:
            if parent is not None and parent.winfo_exists():
                win = tk.Toplevel(parent)
            else:
                win = tk.Tk()
                owns_root = True
        except (tk.TclError, RuntimeError):
            win = tk.Tk()
            owns_root = True

        win.title("Marine Weather Builder - Results")
        
        # Use shared ResultsPopup widget
        gui.ResultsPopup(win, "Execution Results", output_text, readonly=True)
        
        # Bring window to front
        win.lift()
        win.focus_force()
        
        # Run event loop appropriately
        if owns_root:
            win.mainloop()
        else:
            win.wait_window()

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
        update_vis_for_fog = varDict.get("update_vis_for_fog", False)

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
                except (ValueError, TypeError):
                    pass  # Invalid value, keep default

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
        except (ValueError, TypeError, KeyError):
            pass  # Invalid values, keep existing minimum_in
        conv_cfg = _get_safe_convection_cfg()
        cape_cfg = _get_safe_cape_cfg(thunder_thresh)
        cape_cfg["thunder_min"] = max(thunder_thresh, cape_cfg.get("thunder_min", thunder_thresh))
        fog_cfg = _get_safe_fog_cfg()
        fog_rh_min = fog_cfg.get(
            "relative_humidity_min_pct",
            getattr(thresholds, "FOG_THRESHOLDS", {}).get("relative_humidity_min", 85.0),
        )
        conv_idx_thresh = conv_cfg.get("convective_index_threshold", 7.0)
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
        except (AttributeError, ValueError, RuntimeError):
            # Edit area unavailable or invalid; process all grid points
            edit_mask = None

        for i, gridinfo in enumerate(gridinfos):
            grid_tr = gridinfo.gridTime()
            self.statusBarMsg(f"Processing {i+1}/{total_periods}", "R")
            self.log(f"\nPeriod {i+1}/{total_periods}: {grid_tr}")
            # Per-model data availability/logging is emitted inside _get_ensemble_data

            # Get model data
            model_data = self._get_ensemble_data(models, grid_tr, run_depth, create_diag=create_diag)
            if model_data is None:
                continue

            (temp_c, rh, qpf_in, vis_nm, cape, 
             t850_c, t700_c, t500_c, rh850, rh700) = model_data

            # Get forecast wind from Fcst database
            # Returns tuple: (magnitude_knots, direction_degrees) where each is a 2D numpy array
            # wind[0] = magnitude in knots, wind[1] = direction in degrees from north
            wind = self.getGrids("Fcst", "Wind", "SFC", grid_tr, mode="First", noDataError=0)
            
            # ----------------------------------------------------------------
            # Compute stability indices from upper-air data
            # ----------------------------------------------------------------
            lifted_index = None
            k_index = None
            
            # Compute surface dew point for Lifted Index
            if temp_c is not None and rh is not None:
                td_sfc_c = compute_dewpoint_c(temp_c, rh)
            else:
                td_sfc_c = None
            
            # Compute Lifted Index if we have required data
            if temp_c is not None and td_sfc_c is not None and t500_c is not None:
                lifted_index = compute_lifted_index(temp_c, td_sfc_c, t500_c)
                self.log(f"  Lifted Index: min={np.nanmin(lifted_index):.1f}, mean={np.nanmean(lifted_index):.1f}, max={np.nanmax(lifted_index):.1f}")
            
            # Compute K-Index if we have required data
            if t850_c is not None and t700_c is not None and t500_c is not None and rh850 is not None and rh700 is not None:
                td850_c = compute_dewpoint_c(t850_c, rh850)
                td700_c = compute_dewpoint_c(t700_c, rh700)
                k_index = compute_k_index(t850_c, t700_c, t500_c, td850_c, td700_c)
                self.log(f"  K-Index: min={np.nanmin(k_index):.1f}, mean={np.nanmean(k_index):.1f}, max={np.nanmax(k_index):.1f}")

            # Apply smoothing
            if smoothing > 0:
                sigma = smoothing * sigma_base
                if qpf_in is not None:
                    qpf_in = ndimage.gaussian_filter(qpf_in, sigma=sigma, mode="nearest")
                if vis_nm is not None:
                    vis_nm = ndimage.gaussian_filter(vis_nm, sigma=sigma, mode="nearest")

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
                    lifted_index=lifted_index,
                    k_index=k_index,
                    t850_c=t850_c,
                )

            # Determine weather conditions
            has_precip = qpf_in > precip_min if qpf_in is not None else None
            has_thunder = (
                (cape > cape_cfg.get("thunder_min", thunder_thresh)) & (qpf_in > precip_min)
                if (cape is not None and qpf_in is not None)
                else None
            )
            has_fog = (vis_nm < fog_thresh) & (rh > fog_rh_min) if vis_nm is not None and rh is not None else None

            # Optionally update Fcst Visibility grid where fog is detected
            if update_vis_for_fog and has_fog is not None and np.any(has_fog):
                try:
                    vis_fcst = self.getGrids("Fcst", "Visibility", "SFC", grid_tr, mode="First", noDataError=0)
                    if vis_fcst is not None:
                        vis_fcst_out = np.copy(vis_fcst)
                        fog_points = has_fog & edit_mask if edit_mask is not None else has_fog
                        if np.any(fog_points):
                            vis_fcst_out[fog_points] = np.minimum(vis_fcst_out[fog_points], fog_thresh)
                            self.createGrid("Fcst", "Visibility", "SCALAR", vis_fcst_out, grid_tr)
                            self.log(f"  Updated Visibility grid for fog ({np.sum(fog_points)} points)")
                except (ValueError, TypeError) as e:
                    self.log(f"  Warning: Could not update Visibility grid: {e}")

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
            # Thunder coverage now considers BOTH CAPE and QPF:
            # - High QPF + thunder = more organized/widespread convection
            # - High CAPE alone = scattered convection potential
            # - Moderate indicators = isolated
            if np.any(thunder_mask):
                cape_val = cape if cape is not None else np.zeros(wx_values.shape)
                cape_high = float(cape_cfg.get("high", 2000.0))
                cape_moderate = float(cape_cfg.get("moderate", 1000.0))
                cape_severe = float(cape_cfg.get("severe_min", 3000.0))
                severe_with_qpf = float(qpf_cfg.get("severe_with_thunder_in", 1.0))
                
                # QPF thresholds for thunder coverage (reuse precip thresholds)
                qpf_wide = float(qpf_cfg.get("coverage_wide_in", 0.25))
                qpf_num = float(qpf_cfg.get("coverage_numerous_in", 0.10))
                qpf_sct = float(qpf_cfg.get("coverage_scattered_in", 0.03))
                
                # Get QPF values (use zeros if not available)
                qpf_val = qpf_in if qpf_in is not None else np.zeros(wx_values.shape)
                
                # Coverage determination using CAPE and QPF together:
                # Wide: High CAPE AND high QPF (both strong indicators)
                # Num:  High CAPE OR high QPF (one strong indicator) 
                # Sct:  Moderate CAPE or moderate QPF
                # Iso:  Everything else with thunder
                
                high_cape = cape_val > cape_high
                mod_cape = cape_val > cape_moderate
                high_qpf = qpf_val > qpf_wide
                mod_qpf = qpf_val > qpf_num
                low_qpf = qpf_val > qpf_sct
                
                cov_wide = thunder_mask & high_cape & high_qpf
                cov_num = thunder_mask & ~cov_wide & (high_cape | high_qpf)
                cov_sct = thunder_mask & ~(cov_wide | cov_num) & (mod_cape | mod_qpf)
                cov_iso = thunder_mask & ~(cov_wide | cov_num | cov_sct)

                severe = thunder_mask & (cape_val > cape_severe)
                if qpf_in is not None:
                    severe |= thunder_mask & (qpf_in > severe_with_qpf)

                # Note: Wx encoding uses '+' intensity for severe; otherwise <NoInten>
                if np.any(cov_wide & severe):
                    updated_wx[cov_wide & severe] = _idx("Wide:T:+:<NoVis>:")
                if np.any(cov_wide & ~severe):
                    updated_wx[cov_wide & ~severe] = _idx("Wide:T:<NoInten>:<NoVis>:")
                if np.any(cov_num & severe):
                    updated_wx[cov_num & severe] = _idx("Num:T:+:<NoVis>:")
                if np.any(cov_num & ~severe):
                    updated_wx[cov_num & ~severe] = _idx("Num:T:<NoInten>:<NoVis>:")
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
                # Determine convective vs stratiform using stability indices
                # Priority: Lifted Index > K-Index > CAPE-based convective index
                is_conv = np.zeros(wx_values.shape, dtype=bool)
                
                if lifted_index is not None:
                    # Lifted Index: negative = unstable/convective
                    # LI < -2 indicates convective potential
                    is_conv = lifted_index < -2.0
                    self.log(f"  Using Lifted Index for convective determination")
                elif k_index is not None:
                    # K-Index: > 25 indicates convective potential
                    is_conv = k_index > 25.0
                    self.log(f"  Using K-Index for convective determination")
                elif cape is not None and wind is not None:
                    # Fallback to original CAPE-based convective index
                    wind_mag_kt = wind[0]
                    try:
                        wind_ms = thresholds.to_mps(wind_mag_kt)
                    except AttributeError:
                        wind_ms = wind_mag_kt * 0.514444
                    conv_idx = (cape / 1000.0) + (wind_ms / 20.0)
                    is_conv = conv_idx > conv_idx_thresh
                    self.log(f"  Using CAPE-based convective index (fallback)")

                # Precip type determination using both surface and 850mb temperature
                # This enables detection of freezing rain and sleet (warm nose scenarios)
                #
                # Decision matrix:
                # | Sfc Temp | T850    | Precip Type |
                # |----------|---------|-------------|
                # | > 0°C    | any     | Rain (R/RW) |
                # | < 0°C    | < -4°C  | Snow (S/SW) |
                # | < 0°C    | > 0°C   | Freezing Rain (ZR) - warm nose |
                # | < 0°C    | -4 to 0 | Sleet (IP) - partial warm nose |
                
                # Initialize precip type masks
                is_snow = np.zeros(wx_values.shape, dtype=bool)
                is_fzra = np.zeros(wx_values.shape, dtype=bool)  # Freezing rain
                is_sleet = np.zeros(wx_values.shape, dtype=bool)  # Ice pellets
                
                if temp_c is not None and t850_c is not None:
                    # Full winter precip type logic using both levels
                    sfc_below_freezing = temp_c < FREEZING_C
                    sfc_above_freezing = ~sfc_below_freezing
                    
                    # Snow: surface below freezing AND 850mb cold (< -4°C)
                    is_snow = sfc_below_freezing & (t850_c < -4.0)
                    
                    # Freezing rain: surface below freezing BUT 850mb warm (> 0°C)
                    # This is the classic "warm nose" profile
                    is_fzra = sfc_below_freezing & (t850_c > 0.0)
                    
                    # Sleet: surface below freezing, 850mb in transition zone (-4 to 0°C)
                    # Partial warm nose - refreezes before reaching surface
                    is_sleet = sfc_below_freezing & (t850_c >= -4.0) & (t850_c <= 0.0)
                    
                    # Rain: surface above freezing (any 850mb temp)
                    # is_rain is implicit - anything not snow/fzra/sleet with sfc > 0C
                    
                    self.log(f"  Using T850+Sfc for precip type: "
                             f"Snow={np.sum(is_snow & precip_mask)}, "
                             f"ZR={np.sum(is_fzra & precip_mask)}, "
                             f"IP={np.sum(is_sleet & precip_mask)} pts")
                             
                elif t850_c is not None:
                    # Only have T850 - use it for snow determination
                    is_snow = t850_c < -4.0
                    self.log(f"  Using T850 only for precip type (snow where T850 < -4C)")
                elif temp_c is not None:
                    # Fallback to surface temperature only
                    is_snow = temp_c < FREEZING_C
                    self.log(f"  Using surface temp for precip type (fallback)")

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
                inten_plus = precip_mask & (qpf_in > precip_heavy)
                inten_m = precip_mask & ~inten_plus & (qpf_in > precip_moderate)
                inten_minus = precip_mask & ~(inten_plus | inten_m)  # keep '-' as default

                # Coverage/probability masks
                conv_points = precip_mask & is_conv
                strat_points = precip_mask & ~is_conv

                cov_wide = conv_points & (qpf_in > precip_wide)
                cov_num = conv_points & ~cov_wide & (qpf_in > precip_numerous)
                cov_sct = conv_points & ~(cov_wide | cov_num) & (qpf_in > precip_scattered)
                cov_iso = conv_points & ~(cov_wide | cov_num | cov_sct)

                cov_def = strat_points & (qpf_in > precip_definite)
                cov_lkly = strat_points & ~cov_def & (qpf_in > precip_likely)
                cov_chc = strat_points & ~(cov_def | cov_lkly) & (qpf_in > precip_chance)
                cov_schc = strat_points & ~(cov_def | cov_lkly | cov_chc)

                # Pre-build Wx strings with fixed fields
                # Format: "<Cov>:<WxType>:<Inten>:<NoVis>:"
                def wx(cov, typ, inten):
                    return f"{cov}:{typ}:{inten}:<NoVis>:"

                def assign_cov(cov_mask, cov_code, convective: bool):
                    # Determine precip weather type per-point:
                    # - Snow (S/SW), Rain (R/RW), Freezing Rain (ZR), Sleet (IP)
                    # Convective flag determines showers (RW/SW) vs steady (R/S)
                    # Note: ZR and IP don't have convective variants in GFE Wx encoding
                    
                    if convective:
                        rain_type = "RW"
                        snow_type = "SW"
                    else:
                        rain_type = "R"
                        snow_type = "S"

                    # Determine masks for each precip type within this coverage
                    snow_mask = cov_mask & is_snow
                    fzra_mask = cov_mask & is_fzra
                    sleet_mask = cov_mask & is_sleet
                    # Rain is everything else (not snow, not fzra, not sleet)
                    rain_mask = cov_mask & ~is_snow & ~is_fzra & ~is_sleet

                    # Assign rain
                    if np.any(rain_mask & inten_plus):
                        updated_wx[rain_mask & inten_plus] = _idx(wx(cov_code, rain_type, "+"))
                    if np.any(rain_mask & inten_m):
                        updated_wx[rain_mask & inten_m] = _idx(wx(cov_code, rain_type, "m"))
                    if np.any(rain_mask & inten_minus):
                        updated_wx[rain_mask & inten_minus] = _idx(wx(cov_code, rain_type, "-"))

                    # Assign snow
                    if np.any(snow_mask & inten_plus):
                        updated_wx[snow_mask & inten_plus] = _idx(wx(cov_code, snow_type, "+"))
                    if np.any(snow_mask & inten_m):
                        updated_wx[snow_mask & inten_m] = _idx(wx(cov_code, snow_type, "m"))
                    if np.any(snow_mask & inten_minus):
                        updated_wx[snow_mask & inten_minus] = _idx(wx(cov_code, snow_type, "-"))

                    # Assign freezing rain (ZR) - no convective variant
                    if np.any(fzra_mask & inten_plus):
                        updated_wx[fzra_mask & inten_plus] = _idx(wx(cov_code, "ZR", "+"))
                    if np.any(fzra_mask & inten_m):
                        updated_wx[fzra_mask & inten_m] = _idx(wx(cov_code, "ZR", "m"))
                    if np.any(fzra_mask & inten_minus):
                        updated_wx[fzra_mask & inten_minus] = _idx(wx(cov_code, "ZR", "-"))

                    # Assign sleet/ice pellets (IP) - no convective variant
                    if np.any(sleet_mask & inten_plus):
                        updated_wx[sleet_mask & inten_plus] = _idx(wx(cov_code, "IP", "+"))
                    if np.any(sleet_mask & inten_m):
                        updated_wx[sleet_mask & inten_m] = _idx(wx(cov_code, "IP", "m"))
                    if np.any(sleet_mask & inten_minus):
                        updated_wx[sleet_mask & inten_minus] = _idx(wx(cov_code, "IP", "-"))

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
        """
        Get averaged model data using alias configuration.
        
        Returns:
            Tuple of (temp_c, rh, qpf_in, vis_nm, cape, t850_c, t700_c, t500_c, rh850, rh700)
            or None if insufficient data.
        """
        temp_sum, rh_sum, qpf_sum, vis_min, cape_max = None, None, None, None, None
        t850_sum, t700_sum, t500_sum = None, None, None
        rh850_sum, rh700_sum = None, None
        temp_cnt, rh_cnt, qpf_cnt = 0, 0, 0
        t850_cnt, t700_cnt, t500_cnt = 0, 0, 0
        rh850_cnt, rh700_cnt = 0, 0

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

            # ----------------------------------------------------------------
            # Upper-air data for stability indices (LI, K-Index) and precip type
            # ----------------------------------------------------------------
            
            # 850mb Temperature (for K-Index and precipitation type)
            t850 = grid_fetch.get_grid_with_fallback(
                self, alias, temp_elems, ["MB850"], grid_tr, run_depth=run_depth, noDataError=0
            )
            if t850 is not None:
                _, t850_c = _to_f_and_c(t850)
                t850_sum = t850_c if t850_sum is None else t850_sum + t850_c
                t850_cnt += 1

            # 700mb Temperature (for K-Index)
            t700 = grid_fetch.get_grid_with_fallback(
                self, alias, temp_elems, ["MB700"], grid_tr, run_depth=run_depth, noDataError=0
            )
            if t700 is not None:
                _, t700_c = _to_f_and_c(t700)
                t700_sum = t700_c if t700_sum is None else t700_sum + t700_c
                t700_cnt += 1

            # 500mb Temperature (for Lifted Index and K-Index)
            t500 = grid_fetch.get_grid_with_fallback(
                self, alias, temp_elems, ["MB500"], grid_tr, run_depth=run_depth, noDataError=0
            )
            if t500 is not None:
                _, t500_c = _to_f_and_c(t500)
                t500_sum = t500_c if t500_sum is None else t500_sum + t500_c
                t500_cnt += 1

            # 850mb RH (for K-Index dew point)
            rh850 = grid_fetch.get_grid_with_fallback(
                self, alias, rh_elems, ["MB850"], grid_tr, run_depth=run_depth, noDataError=0
            )
            if rh850 is not None:
                rh850_sum = rh850 if rh850_sum is None else rh850_sum + rh850
                rh850_cnt += 1

            # 700mb RH (for K-Index dew point)
            rh700 = grid_fetch.get_grid_with_fallback(
                self, alias, rh_elems, ["MB700"], grid_tr, run_depth=run_depth, noDataError=0
            )
            if rh700 is not None:
                rh700_sum = rh700 if rh700_sum is None else rh700_sum + rh700
                rh700_cnt += 1

            if temp is not None:
                temp_stats = (float(np.nanmin(temp_c)), float(np.nanmean(temp_c)), float(np.nanmax(temp_c)))

            # Summarize per-model availability for this time
            parts = [f"{alias}: "]
            parts.append(f"T {temp_stats[0]:.1f}/{temp_stats[1]:.1f}/{temp_stats[2]:.1f} C" if temp_stats else "T missing")
            parts.append(f"RH {rh_stats[0]:.0f}/{rh_stats[1]:.0f}/{rh_stats[2]:.0f}%" if rh_stats else "RH missing")
            parts.append(f"QPF {qpf_stats[0]:.2f}/{qpf_stats[1]:.2f}/{qpf_stats[2]:.2f}\"" if qpf_stats else "QPF missing")
            parts.append(f"Vsby {vis_stats[0]:.2f}/{vis_stats[1]:.2f}/{vis_stats[2]:.2f} nm" if vis_stats else "Vsby missing")
            parts.append(f"CAPE {cape_stats[0]:.0f}/{cape_stats[1]:.0f}/{cape_stats[2]:.0f} J/kg" if cape_stats else "CAPE missing")
            # Log upper-air availability
            ua_parts = []
            if t850_cnt > 0:
                ua_parts.append("T850")
            if t700_cnt > 0:
                ua_parts.append("T700")
            if t500_cnt > 0:
                ua_parts.append("T500")
            if ua_parts:
                parts.append(f"UA: {'/'.join(ua_parts)}")
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
        
        # Upper-air averages
        t850_avg = t850_sum / t850_cnt if t850_cnt > 0 else None
        t700_avg = t700_sum / t700_cnt if t700_cnt > 0 else None
        t500_avg = t500_sum / t500_cnt if t500_cnt > 0 else None
        rh850_avg = rh850_sum / rh850_cnt if rh850_cnt > 0 else None
        rh700_avg = rh700_sum / rh700_cnt if rh700_cnt > 0 else None

        return (temp_avg, rh_avg, qpf_avg, vis_min, cape_max, 
                t850_avg, t700_avg, t500_avg, rh850_avg, rh700_avg)

    def _create_diagnostics(self, grid_tr, temp_c, rh, qpf_in, vis_nm, cape, wind, clip, conv_idx_thresh,
                             *, lifted_index=None, k_index=None, t850_c=None):
        """Create diagnostic grids including stability indices."""
        # Use fixed, predictable ranges for diagnostics to ensure display limits stick
        qpf_max = 1.0
        cape_max = 5000.0
        temp_min_f, temp_max_f = -50.0, 130.0
        rh_min, rh_max = 0.0, 100.0
        vis_min, vis_max = 0.0, 10.0
        conv_clip_min, conv_clip_max = 0.0, 10.0
        li_min, li_max = -15.0, 15.0  # Lifted Index range
        k_min, k_max = 0.0, 50.0      # K-Index range

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

        # Stability indices
        if lifted_index is not None:
            li_clipped = np.clip(lifted_index, li_min, li_max)
            self.createGrid(
                "Fcst",
                "modelLI",
                "SCALAR",
                li_clipped,
                grid_tr,
                minAllowedValue=li_min,
                maxAllowedValue=li_max,
                units="C",
                descriptiveName="Lifted Index",
            )

        if k_index is not None:
            k_clipped = np.clip(k_index, k_min, k_max)
            self.createGrid(
                "Fcst",
                "modelKIndex",
                "SCALAR",
                k_clipped,
                grid_tr,
                minAllowedValue=k_min,
                maxAllowedValue=k_max,
                descriptiveName="K-Index",
            )

        if t850_c is not None:
            try:
                t850_f = thresholds.c_to_f(t850_c)
            except AttributeError:
                t850_f = t850_c * 9.0/5.0 + 32.0
            t850_f_clipped = np.clip(t850_f, temp_min_f, temp_max_f)
            self.createGrid(
                "Fcst",
                "modelT850",
                "SCALAR",
                t850_f_clipped,
                grid_tr,
                minAllowedValue=temp_min_f,
                maxAllowedValue=temp_max_f,
                units="F",
                descriptiveName="850mb Temperature",
            )

__all__ = ["Procedure"]

