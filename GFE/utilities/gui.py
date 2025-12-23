"""
Reusable Tkinter widgets shared by Smart Tools.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

import model_aliases

# Module-level logger for debugging
_logger = logging.getLogger(__name__)


def _safe_callback(callback: Optional[Callable], *args, **kwargs):
    if callback is None:
        return
    try:
        callback(*args, **kwargs)
    except Exception as e:
        _logger.error(f"Callback error in gui component: {e}", exc_info=True)


def _validate_range(value: float, min_val: float, max_val: float, name: str) -> float:
    if value < min_val:
        _logger.warning(f"{name} value {value} below minimum {min_val}, clamping")
        return min_val
    if value > max_val:
        _logger.warning(f"{name} value {value} above maximum {max_val}, clamping")
        return max_val
    return value


class ModelSelectionFrame(tk.LabelFrame):
    """Checkbox group for selecting atmospheric/wave models by alias."""

    def __init__(
        self,
        master,
        *,
        title: str = "Select Models",
        models: Sequence[Tuple[str, str]] | None = None,
        default_selected: Iterable[str] | None = None,
        on_change: Callable[[List[str]], None] | None = None,
    ):
        super().__init__(master, text=title, padx=10, pady=10)
        self._on_change = on_change

        validate_aliases = models is None

        # Safe model list retrieval
        if models is None:
            try:
                model_list = model_aliases.list_models("atmo")
                models = [(alias, alias) for alias in model_list]
            except Exception as e:
                _logger.error(f"Failed to get model list: {e}", exc_info=True)
                models = []

        defaults = {model_key.upper() for model_key in (default_selected or [])}
        self._variables: dict[str, tk.StringVar] = {}

        for display, key in models:
            normalized = key.upper()
            try:
                if validate_aliases and not model_aliases.has_alias(normalized):
                    _logger.debug(f"Skipping unknown alias: {normalized}")
                    continue
            except Exception as e:
                # If we can't validate aliases (or the registry isn't available),
                # still render explicitly provided options so the GUI isn't empty.
                _logger.warning(f"Error checking alias {normalized}: {e}")
                if validate_aliases:
                    continue

            var = tk.StringVar(value="Yes" if normalized in defaults else "No")
            chk = tk.Checkbutton(
                self,
                text=display,
                anchor=tk.W,
                variable=var,
                onvalue="Yes",
                offvalue="No",
                command=self._notify_change,
            )
            chk.pack(fill=tk.X, pady=2)
            self._variables[normalized] = var

        if not self._variables:
            tk.Label(
                self, text="No models available", font=("Arial", 9), fg="gray"
            ).pack(anchor=tk.W)

    def _notify_change(self):
        _safe_callback(self._on_change, self.get_selected_models())

    def get_selected_models(self) -> List[str]:
        """Return list of selected model aliases (uppercase)."""
        return [key for key, var in self._variables.items() if var.get() == "Yes"]


class ModelSelectionWithRunsFrame(tk.LabelFrame):
    """Model selection with checkboxes and run depth spinboxes (for consensus tools)."""

    def __init__(
        self,
        master,
        *,
        title: str = "Select Models for Consensus",
        models: Sequence[Tuple[str, str, int]] | None = None,
        default_selected: Iterable[str] | None = None,
        on_change: Callable[[], None] | None = None,
    ):
        super().__init__(master, text=title, padx=15, pady=10)
        self._on_change = on_change
        defaults = {m.upper() for m in (default_selected or [])}

        tk.Label(
            self, text="Select models and number of runs (depth) to include", font=("Arial", 9), fg="gray"
        ).pack(anchor=tk.W, pady=(0, 5))

        # Grid header
        header = tk.Frame(self)
        header.pack(fill=tk.X, pady=2)
        tk.Label(header, text="Model", width=25, anchor="w", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        tk.Label(header, text="Runs", width=10, anchor="w", font=("Arial", 9, "bold")).pack(side=tk.LEFT)

        self._model_info: dict[str, dict] = {}
        models = models or []

        for alias, display_name, max_runs in models:
            # Validate max_runs
            if max_runs < 1:
                _logger.warning(f"Invalid max_runs {max_runs} for {alias}, using 1")
                max_runs = 1

            row = tk.Frame(self)
            row.pack(fill=tk.X, pady=2)

            var = tk.StringVar(value="Yes" if alias.upper() in defaults else "No")
            runs_var = tk.IntVar(value=1)

            # Fix lambda closure issue by capturing alias in default parameter
            def make_trace(alias_key: str):
                def trace_callback(*args):
                    _safe_callback(self._on_change)
                return trace_callback

            if self._on_change:
                var.trace("w", make_trace(alias.upper()))
                runs_var.trace("w", make_trace(alias.upper()))

            self._model_info[alias.upper()] = {
                "displayName": display_name,
                "maxRuns": max_runs,
                "selectedVar": var,
                "runsVar": runs_var,
            }

            tk.Checkbutton(
                row, text=f"{display_name} ({alias})", variable=var, onvalue="Yes", offvalue="No", font=("Arial", 10), width=25, anchor="w"
            ).pack(side=tk.LEFT)
            tk.Spinbox(row, from_=1, to=max_runs, textvariable=runs_var, width=3).pack(side=tk.LEFT)

        if not self._model_info:
            tk.Label(
                self, text="No models configured", font=("Arial", 9), fg="gray"
            ).pack(anchor=tk.W)

    def get_selected_models(self) -> dict[str, dict]:
        """Return dict of {alias: {"displayName": str, "runs": int}} for selected models."""
        result = {}
        for alias, info in self._model_info.items():
            if info["selectedVar"].get() == "Yes":
                result[alias] = {
                    "displayName": info["displayName"],
                    "runs": info["runsVar"].get(),
                }
        return result


class StatusBanner(tk.Frame):
    """Two-line status banner (bold title + helper text)."""

    def __init__(self, master, *, width: int = 40):
        super().__init__(master)
        self.status_label = tk.Label(self, font=("Arial", 11, "bold"), fg="green", width=width)
        self.status_label.pack()
        self.message_label = tk.Label(self, font=("Arial", 9), fg="green", width=width)
        self.message_label.pack()

    def set_status(self, text: str, color: str = "green"):
        self.status_label.config(text=text, fg=color)

    def set_message(self, text: str, color: str = "green"):
        self.message_label.config(text=text, fg=color)


class SmoothingSlider(tk.Frame):
    """Horizontal slider for smoothing strength (0-5 default)."""

    def __init__(self, master, *, min_value: int = 0, max_value: int = 5, default: int = 2, label: str = "Spatial Smoothing"):
        super().__init__(master)
        
        # Validate and clamp default
        default = int(_validate_range(default, min_value, max_value, "SmoothingSlider default"))
        
        tk.Label(self, text=label, font=("Arial", 10, "bold")).pack(anchor=tk.W)
        self.var = tk.IntVar(value=default)
        tk.Scale(
            self,
            from_=min_value,
            to=max_value,
            orient=tk.HORIZONTAL,
            variable=self.var,
            length=220,
        ).pack(anchor=tk.W)

    def get_value(self) -> int:
        return int(self.var.get())


class ThresholdSlider(tk.Frame):
    """Generic slider with label, scale, and optional helper text. Supports both IntVar and DoubleVar."""

    def __init__(
        self,
        master,
        *,
        label: str,
        min_value: float,
        max_value: float,
        default: float,
        resolution: float = 1.0,
        helper_text: str | None = None,
        var_type: type = float,
    ):
        super().__init__(master)
        
        # Validate inputs
        if min_value >= max_value:
            raise ValueError(f"min_value ({min_value}) must be < max_value ({max_value})")
        if resolution <= 0:
            raise ValueError(f"resolution ({resolution}) must be > 0")
        
        # Validate and clamp default
        default = _validate_range(default, min_value, max_value, "ThresholdSlider default")
        
        tk.Label(self, text=label, font=("Arial", 10, "bold")).pack(anchor=tk.W)

        if var_type == int:
            self.var = tk.IntVar(value=int(default))
        else:
            self.var = tk.DoubleVar(value=float(default))

        row = tk.Frame(self)
        row.pack(fill=tk.X)
        tk.Scale(
            row,
            from_=min_value,
            to=max_value,
            resolution=resolution,
            orient=tk.HORIZONTAL,
            variable=self.var,
            length=200,
        ).pack(side=tk.LEFT)

        if helper_text:
            tk.Label(row, text=helper_text, font=("Arial", 8), fg="gray").pack(side=tk.LEFT, padx=(10, 0))

    def get_value(self) -> float:
        return float(self.var.get())


class WeightSliderGroup(tk.Frame):
    """Group of weight sliders with percentage labels (for model blending)."""

    def __init__(
        self,
        master,
        *,
        title: str = "Model Weights",
        models: Sequence[Tuple[str, str]],
        min_weight: int = 0,
        max_weight: int = 10,
        default_weight: int = 0,
        on_change: Callable[[], None] | None = None,
    ):
        super().__init__(master)
        
        # Validate inputs
        if not models:
            raise ValueError("models sequence cannot be empty")
        if min_weight >= max_weight:
            raise ValueError(f"min_weight ({min_weight}) must be < max_weight ({max_weight})")
        default_weight = int(_validate_range(default_weight, min_weight, max_weight, "WeightSliderGroup default_weight"))
        
        frame = tk.LabelFrame(self, text=title, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        self._weight_vars: dict[str, tk.IntVar] = {}
        self._pct_labels: dict[str, tk.Label] = {}
        self._on_change = on_change

        for alias, display_name in models:
            row = tk.Frame(frame)
            row.pack(fill=tk.X, pady=3)

            var = tk.IntVar(value=default_weight)
            self._weight_vars[alias] = var

            tk.Label(row, text=f"{display_name}:", width=20, anchor=tk.W).pack(side=tk.LEFT)
            tk.Scale(
                row,
                from_=min_weight,
                to=max_weight,
                orient=tk.HORIZONTAL,
                variable=var,
                command=lambda _: self._update_percentages(),
                width=15,
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

            pct_label = tk.Label(row, text="0%", width=6)
            pct_label.pack(side=tk.RIGHT)
            self._pct_labels[alias] = pct_label

        self._update_percentages()

    def _update_percentages(self):
        total = sum(v.get() for v in self._weight_vars.values())
        for alias, var in self._weight_vars.items():
            if total == 0:
                self._pct_labels[alias].config(text="0%")
            else:
                # Avoid division by zero (already checked, but defensive)
                pct = int(100 * var.get() / total) if total > 0 else 0
                self._pct_labels[alias].config(text=f"{pct}%")
        _safe_callback(self._on_change)

    def get_weights(self) -> dict[str, int]:
        return {alias: var.get() for alias, var in self._weight_vars.items()}


class RadioGroup(tk.Frame):
    """Group of radio buttons with optional helper text."""

    def __init__(
        self,
        master,
        *,
        title: str | None = None,
        options: Sequence[Tuple[str, str]],  # (value, label)
        default: str,
        orientation: str = "vertical",  # "vertical" or "horizontal"
        helper_texts: dict[str, str] | None = None,  # {value: helper_text}
    ):
        super().__init__(master)
        
        # Validate inputs
        if not options:
            raise ValueError("options sequence cannot be empty")
        option_values = {opt[0] for opt in options}
        if default not in option_values:
            raise ValueError(f"default value '{default}' not in options")
        if orientation not in ("vertical", "horizontal"):
            raise ValueError(f"orientation must be 'vertical' or 'horizontal', got '{orientation}'")
        
        if title:
            frame = tk.LabelFrame(self, text=title, padx=10, pady=10)
            frame.pack(fill=tk.BOTH, expand=True)
            container = frame
        else:
            container = self

        self.var = tk.StringVar(value=default)
        helper_texts = helper_texts or {}

        for value, label in options:
            if orientation == "horizontal":
                row = tk.Frame(container)
                row.pack(side=tk.LEFT, padx=5)
                tk.Radiobutton(row, text=label, variable=self.var, value=value).pack(side=tk.LEFT)
            else:
                tk.Radiobutton(container, text=label, variable=self.var, value=value).pack(anchor=tk.W)
                if value in helper_texts:
                    tk.Label(
                        container, text=f"  • {helper_texts[value]}", font=("Arial", 9), fg="gray"
                    ).pack(anchor=tk.W, padx=(20, 0))

    def get_value(self) -> str:
        return self.var.get()


class CheckboxGroup(tk.Frame):
    """Group of checkboxes with optional helper text."""

    def __init__(
        self,
        master,
        *,
        title: str | None = None,
        options: Sequence[Tuple[str, str]],  # (value, label)
        default_selected: Iterable[str] | None = None,
        helper_texts: dict[str, str] | None = None,
    ):
        super().__init__(master)
        
        # Validate inputs
        if not options:
            raise ValueError("options sequence cannot be empty")
        
        if title:
            frame = tk.LabelFrame(self, text=title, padx=10, pady=10)
            frame.pack(fill=tk.BOTH, expand=True)
            container = frame
        else:
            container = self

        defaults = {v.upper() for v in (default_selected or [])}
        self._vars: dict[str, tk.BooleanVar] = {}
        helper_texts = helper_texts or {}

        for value, label in options:
            var = tk.BooleanVar(value=value.upper() in defaults)
            self._vars[value.upper()] = var
            tk.Checkbutton(container, text=label, variable=var).pack(anchor=tk.W)
            if value.upper() in helper_texts:
                tk.Label(
                    container, text=f"  • {helper_texts[value.upper()]}", font=("Arial", 9), fg="gray"
                ).pack(anchor=tk.W, padx=(20, 0))

    def get_selected(self) -> List[str]:
        return [value for value, var in self._vars.items() if var.get()]

    def get_value(self, option: str) -> bool:
        return self._vars.get(option.upper(), tk.BooleanVar(value=False)).get()


class ButtonFrame(tk.Frame):
    """Standard button frame with Run/Cancel buttons."""

    def __init__(
        self,
        master,
        *,
        run_text: str = "Run Tool",
        run_command: Callable[[], None],
        cancel_command: Callable[[], None],
        run_color: str = "lightgreen",
        cancel_text: str = "Cancel",
    ):
        super().__init__(master)
        
        if run_command is None or cancel_command is None:
            raise ValueError("run_command and cancel_command are required")
        
        tk.Button(
            self, text=run_text, command=run_command, bg=run_color, font=("Arial", 11, "bold"), width=15
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(self, text=cancel_text, command=cancel_command, width=12).pack(side=tk.LEFT)


class TwoColumnLayout(tk.Frame):
    """Helper for creating two-column layouts."""

    def __init__(self, master, *, padx: int = 10):
        super().__init__(master)
        if padx < 0:
            raise ValueError(f"padx must be >= 0, got {padx}")
        self.left = tk.Frame(self)
        self.left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, padx))
        self.right = tk.Frame(self)
        self.right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(padx, 0))


class ResultsPopup:
    """Scrollable text popup for diagnostic summaries and debugging."""

    def __init__(self, master, title: str, output_text: str = "", *, readonly: bool = False):
        if not title:
            raise ValueError("title cannot be empty")
        if output_text is None:
            output_text = ""
        
        self.master = master
        self.master.title(title)
        self.master.geometry("900x700")
        self._readonly = readonly

        main_frame = tk.Frame(self.master, padx=10, pady=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(main_frame, text=title, font=("Arial", 14, "bold")).pack(pady=(0, 10))

        text_frame = tk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.text_widget = tk.Text(
            text_frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=("Courier", 9)
        )
        self.text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.text_widget.yview)

        # Insert text before setting readonly state
        if output_text:
            self.text_widget.insert("1.0", output_text)
        else:
            self.text_widget.insert("1.0", "No output available.")
        
        # Scroll to top to show content
        self.text_widget.see("1.0")
        
        # Set readonly state after inserting text
        if readonly:
            self.text_widget.config(state=tk.DISABLED)

        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        if not readonly:
            tk.Button(button_frame, text="Clear", command=self.clear, width=15).pack(side=tk.LEFT, padx=(0, 5))
        
        tk.Button(button_frame, text="Copy to Clipboard", command=self.copy_to_clipboard, width=20).pack(
            side=tk.RIGHT, padx=(0, 10)
        )
        close_btn = tk.Button(button_frame, text="Close", command=lambda: self.master.destroy(), width=15)
        close_btn.pack(side=tk.RIGHT)
        
        # Also allow closing with Escape key
        self.master.bind("<Escape>", lambda e: self.master.destroy())

    def append(self, text: str):
        """Append text to the popup (for debugging)."""
        if self._readonly:
            self.text_widget.config(state=tk.NORMAL)
        self.text_widget.insert(tk.END, text)
        self.text_widget.see(tk.END)  # Auto-scroll to bottom
        if self._readonly:
            self.text_widget.config(state=tk.DISABLED)
        self.master.update_idletasks()  # Force UI update

    def clear(self):
        """Clear all text from the popup."""
        if self._readonly:
            self.text_widget.config(state=tk.NORMAL)
        self.text_widget.delete("1.0", tk.END)
        if self._readonly:
            self.text_widget.config(state=tk.DISABLED)

    def get_text(self) -> str:
        """Get all text content."""
        return self.text_widget.get("1.0", tk.END)

    def copy_to_clipboard(self):
        try:
            self.master.clipboard_clear()
            self.master.clipboard_append(self.get_text())
        except Exception as e:
            _logger.error(f"Failed to copy to clipboard: {e}", exc_info=True)


__all__ = [
    "ModelSelectionFrame",
    "ModelSelectionWithRunsFrame",
    "StatusBanner",
    "SmoothingSlider",
    "ThresholdSlider",
    "WeightSliderGroup",
    "RadioGroup",
    "CheckboxGroup",
    "ButtonFrame",
    "TwoColumnLayout",
    "ResultsPopup",
]
