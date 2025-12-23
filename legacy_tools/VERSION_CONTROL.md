# Version Control System

## File Structure

- **OutOfDomainSpot_current.py** - Stable, production-ready version
  - This is the tested, working version that should be used in production
  - Only update this file when the working version is fully tested and stable
  
- **OutOfDomainSpot.py** - Working/development version
  - This is where active development and testing happens
  - Marked as "WORKING VERSION - DO NOT USE IN PRODUCTION" in the header
  - All new features and fixes are developed here first

## Workflow

1. **Starting new work**: Work on `OutOfDomainSpot.py` (the working version)
2. **Testing**: Test all changes thoroughly in the working version
3. **Promoting to stable**: Once tested and verified:
   - Copy `OutOfDomainSpot.py` to `OutOfDomainSpot_current.py`
   - Update version numbers and headers appropriately
   - The working version becomes the new stable version

## Version History

- **v1.0** (Current Stable)
  - Initial stable release with custom tkinter GUI
  - Multi-model ensemble support (GFS, ECMWF, CMC)
  - CSV output with manual editing option
  - Meteogram generation with error bars
  - Intranet delivery support

