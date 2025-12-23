"""
NoGreaterThan - Limit grid values to a maximum threshold.

Modularized version using shared utilities.
Original Author: Matthew H. Belk (WFO Taunton, MA)
"""

from __future__ import annotations

import numpy as np

import SmartScript

ToolType = "numeric"
WeatherElementEdited = "variableElement"
HideTool = 0

VariableList = [
    ("Enter maximum value:", "", "numeric"),
    ("Vector Component", "Magnitude", "radio", ["Magnitude", "Direction"]),
]


class Tool(SmartScript.SmartScript):
    """Ensures value of field is not greater than specified maximum."""

    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)

    def preProcessTool(self, editArea):
        """Save and set vector edit mode."""
        self._savedMode = self.getVectorEditMode()
        self.setVectorEditMode("Both")

    def execute(self, variableElement, variableElement_GridInfo, varDict):
        """Limit values to the specified maximum."""
        max_value = varDict["Enter maximum value:"]
        vector_component = varDict["Vector Component"]

        # Direction must be 1-360
        if vector_component == "Direction":
            max_value = np.clip(max_value, 1, 360)
            if max_value == 0:
                max_value = 360

        wx_type = str(variableElement_GridInfo.getGridType())

        if wx_type == "SCALAR":
            variableElement = np.where(variableElement > max_value, max_value, variableElement)

        elif wx_type == "VECTOR":
            mag, direction = variableElement

            if vector_component == "Magnitude":
                mag = np.where(mag > max_value, max_value, mag)
            else:
                # Fix zero directions where magnitude > 0
                direction = np.where((mag > 0.0) & (direction == 0.0), 360.0, direction)
                direction = np.where(direction > max_value, max_value, direction)

            variableElement = (mag, direction)

        return variableElement

    def postProcessTool(self):
        """Restore vector edit mode."""
        self.setVectorEditMode(self._savedMode)


__all__ = ["Tool"]

