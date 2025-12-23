# ----------------------------------------------------------------------------
# This software is in the public domain, furnished "as is", without technical
# support, and with no warranty, express or implied, as to its usefulness for
# any purpose.
#
# NoGreaterThan
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

VariableList = [('Enter maximum value:', '', 'numeric'),
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
        "Ensures value of field is not > specified maximum."
        
        # Get maximum numeric value
        maxValue = varDict['Enter maximum value:']

        # Get vector component to modify - if this field is a vector
        self._vectorComponent = varDict['Vector Component']

        # Ensure limit makes sense for a 'direction' vector component
        if self._vectorComponent == 'Direction':

            #  Vector direction can't be less than 1 or greater than 360 degrees
            if maxValue < 1:
                maxValue = 1
            elif maxValue > 360:
                maxValue = 360
            elif maxValue == 0:
                maxValue = 360
        
        # Determine the type of this variable
        wxType = str(variableElement_GridInfo.getGridType())
        print("wxType:", wxType)
        # If this variable is a SCALAR type
        if wxType == "SCALAR":
            print("found scalar")
            # Limit values of this grid
            variableElement[variableElement > maxValue] = maxValue

        # If this variable is a VECTOR type
        elif wxType == "VECTOR":
            print("found vector")
            # Split this vector into its components
            (mag, dir) = variableElement

            # If we are modifying the 'Magnitude'
            if self._vectorComponent == 'Magnitude':
                print("working on mag")
                # Limit 'Magnitudes' of this grid
                mag[mag > maxValue] = maxValue

            # Otherwise, modify the direction
            else:
                print("working on dir")
                # Fix vector direction where vector magnitude is > 0
                dir[(mag > 0.0) & (dir == 0.0)] = 360.0
                print(maxValue)
                # Limit 'Directions' of this grid
                dir[dir > maxValue] = maxValue

            # Put the vector back together
            variableElement = (mag, dir)


        # Return the new value
        return variableElement

    # Set edit mod value to whatever it was before we ran this tool
    def postProcessTool(self):
        self.setVectorEditMode(self.savemode)