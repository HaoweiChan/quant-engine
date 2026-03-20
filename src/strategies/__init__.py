"""User-editable strategy implementations.

This directory is the sandbox for custom trading strategies. Each file
implements one or more policy classes that plug into PositionEngine:

- EntryPolicy  — decides when and how to open a new position
- AddPolicy    — decides when to pyramid / add to a winning position
- StopPolicy   — sets initial stop-loss and trailing stop logic

Edit these files freely in the dashboard's Strategy tab. The engine
validation step will verify your changes compile and instantiate correctly.

Core system modules (src/core/) are NOT editable from the dashboard.
"""
