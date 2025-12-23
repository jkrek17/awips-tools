# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# NoLessThan
#
# Author:  Matthew H. Belk      WFO Taunton, MA         Created: 03/04/2002
#                                                 Last Modified: 11/14/2002
#
# Ported to AWIPS II by Tom LeFebvre
#
# ----------------------------------------------------------------------------

ToolType = "numeric"
WeatherElementEdited = "variableElement"
import numpy as np
HideTool = 0

ScreenList = ["SCALAR", "VECTOR"]

# Set up variables to be solicited from the user:
VariableList = [('Enter minimum value:', '', 'numeric'),
                ('Vector Component', 'Magnitude', 'radio',
                 ['Magnitude', 'Direction']),
               ]

# Set up Class
import SmartScript

class Tool(SmartScript.SmartScript):
    def __init__(self, dbss):
        SmartScript.SmartScript.__init__(self, dbss)


    def preProcessTool(self, editArea):
        # Set edit mode to both
        self.savemode=self.getVectorEditMode()
        self.setVectorEditMode("Both")
        
    def execute(self, variableElement, variableElement_GridInfo, varDict):
        "Ensures value of field is not < specified minimum."

        # Get minimum numeric value
        minValue = varDict['Enter minimum value:']

        # Get vector component to modify - if this field is a vector
        self._vectorComponent = varDict['Vector Component']

        # Ensure limit makes sense for a 'direction' vector component
        if self._vectorComponent == 'Direction':

            #  Vector direction can't be less than 1 or greater than 360 degrees
            if minValue < 1:
                minValue = 1
            elif minValue > 360:
                minValue = 360
            elif minValue == 0:
                minValue = 360

        # Determine the type of this variable
        wxType = str(variableElement_GridInfo.getGridType())
        # If this variable is a SCALAR type
        if wxType == "SCALAR":

            # Limit values of this grid
            variableElement[variableElement < minValue] = minValue

        # If this variable is a VECTOR type
        elif wxType == "VECTOR":

            # Split this vector into its components
            (mag, dir) = variableElement

            # If we are modifying the 'Magnitude'
            if self._vectorComponent == 'Magnitude':

                # Limit 'Magnitudes' of this grid
                mask = mag < minValue
                mag[mag < minValue] = minValue

            # Otherwise, modify the direction
            else:

                # Fix vector direction where vector magnitude is > 0
                dir[(mag < 0.0) & (dir == 0.0)] = 360.0

                # Limit 'Directions' of this grid
                mask = dir < minValue
                dir[dir < minValue] = minValue

            # Put the vector back together
            variableElement = (mag, dir)

        else:
            self.statusBarMsg("NoLessThan runs only on SCALAR or VECTOR data types.", "S")

        # Return the new value
        return variableElement

    # Set edit mod value to whatever it was before we ran this tool
    def postProcessTool(self):
        self.setVectorEditMode(self.savemode)
        