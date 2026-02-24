"""Retro CRT color theme and styling constants."""

# Phosphor green palette
GREEN_BRIGHT = (51, 255, 51)
GREEN_MEDIUM = (30, 180, 30)
GREEN_DIM = (15, 90, 15)
GREEN_FAINT = (8, 45, 8)

# Phosphor amber palette
AMBER_BRIGHT = (255, 176, 0)
AMBER_MEDIUM = (180, 124, 0)
AMBER_DIM = (90, 62, 0)
AMBER_FAINT = (45, 31, 0)

# Background
BLACK = (0, 0, 0)
DARK_BG = (5, 5, 5)

# Active palette (default to green phosphor)
TEXT = GREEN_BRIGHT
TEXT_DIM = GREEN_MEDIUM
GRID = GREEN_DIM
GRID_FAINT = GREEN_FAINT
BG = DARK_BG

# Graph trace colors (different brightness levels for multiple traces)
TRACE_BT = GREEN_BRIGHT     # Bean temperature - brightest
TRACE_ET = GREEN_MEDIUM      # Environment temperature
TRACE_ROR = AMBER_BRIGHT     # Rate of rise - amber to distinguish

# Reference profile trace colors (dimmer versions for background overlay)
REF_BT = GREEN_DIM
REF_ET = GREEN_FAINT
REF_ROR = AMBER_DIM
