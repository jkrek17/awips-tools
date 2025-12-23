"""
Marine Out of Domain Spot Forecast Tool.

Re-export of the Marine Spot Forecast tool for backward compatibility.
This module provides the same functionality as Marine_SpotForecast.py under
a different name to maintain compatibility with existing workflows.

Use GFE.smarttools.Marine_SpotForecast for new implementations.
"""

import Marine_SpotForecast

Procedure = Marine_SpotForecast.Procedure
MarineSpotForecastGUI = Marine_SpotForecast.MarineSpotForecastGUI
ENSEMBLE_MODELS = Marine_SpotForecast.ENSEMBLE_MODELS

__all__ = ["Procedure", "MarineSpotForecastGUI", "ENSEMBLE_MODELS"]
