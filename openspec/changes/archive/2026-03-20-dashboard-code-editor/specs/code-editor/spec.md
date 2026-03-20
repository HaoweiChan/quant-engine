## ADDED Requirements

### Requirement: Embedded Ace code editor
The Strategy tab SHALL render an Ace editor component (`dash-ace`) in the main content area with Python syntax highlighting, line numbers, soft-wrap enabled, and a dark theme visually consistent with the dashboard palette. The editor font SHALL be JetBrains Mono at 13px.

#### Scenario: Editor loads with selected file
- **WHEN** the user clicks a file in the file browser sidebar
- **THEN** the Ace editor SHALL load the file contents with appropriate syntax mode (Python for `.py`, TOML for `.toml`) and the filename displayed above the editor

#### Scenario: Editor preserves content on re-selection
- **WHEN** the user switches to a different file and then switches back
- **THEN** the editor SHALL reload the file from disk (not from a stale cache)

### Requirement: File browser sidebar
The Strategy tab sidebar SHALL list all editable files under `src/strategies/` as a grouped flat list. Files SHALL be grouped by subdirectory (root, configs/). The currently selected file SHALL be visually highlighted.

#### Scenario: File list populates on tab load
- **WHEN** the user navigates to the Strategy tab
- **THEN** the sidebar SHALL display all Python and TOML files from `src/strategies/` grouped by directory

#### Scenario: Selecting a file loads it into the editor
- **WHEN** the user clicks a filename in the sidebar
- **THEN** the editor SHALL display that file's contents and the filename header SHALL update

#### Scenario: Empty directory handling
- **WHEN** an allowed directory contains no editable files
- **THEN** that directory group SHALL not appear in the sidebar

### Requirement: File save capability
The editor SHALL provide a "Save" button that writes the current editor contents back to the file on disk. The save operation SHALL validate that the target path is within `src/strategies/` before writing.

#### Scenario: Save writes to disk
- **WHEN** the user clicks "Save"
- **THEN** the file on disk SHALL be updated with the editor contents and a success indicator SHALL appear

#### Scenario: Save blocked for disallowed path
- **WHEN** a save is attempted for a path outside `src/strategies/`
- **THEN** the save SHALL be rejected and an error message SHALL appear

#### Scenario: Revert to last saved version
- **WHEN** the user clicks "Revert"
- **THEN** the editor SHALL reload the file contents from disk, discarding unsaved changes

### Requirement: Modified file indicator
The editor SHALL track which files have been saved since the last backtest run. When one or more strategy files have been modified, a visual indicator SHALL appear on the Backtest tab label (e.g., "Backtest •").

#### Scenario: Backtest tab shows stale indicator after save
- **WHEN** the user saves a file in the Strategy editor
- **THEN** the Backtest tab label SHALL display "Backtest •" until the next backtest is run

#### Scenario: Indicator clears after backtest run
- **WHEN** the user runs a backtest after modifying files
- **THEN** the stale indicator on the Backtest tab label SHALL be removed

### Requirement: Syntax validation on save
Before writing to disk, the save operation SHALL parse the editor contents using `ast.parse()`. If parsing fails, the save SHALL still proceed but the validation panel SHALL display the syntax error with line number and message.

#### Scenario: Valid syntax on save
- **WHEN** the user saves a file with valid Python syntax
- **THEN** the validation panel SHALL show "Syntax OK" in green

#### Scenario: Syntax error on save
- **WHEN** the user saves a file with a SyntaxError
- **THEN** the file SHALL still be saved but the validation panel SHALL display the error in red

### Requirement: Ruff lint on save
After saving a `.py` file, the editor SHALL run `ruff check` on the saved content and display lint results in the validation panel. Results SHALL show rule code, line number, and message.

#### Scenario: Clean lint result
- **WHEN** the user saves a file with no lint issues
- **THEN** the validation panel SHALL show "Lint: clean" in green

#### Scenario: Lint issues found
- **WHEN** the user saves a file and ruff reports warnings
- **THEN** the validation panel SHALL list each issue with rule code, line number, and description

### Requirement: Engine validation on save
After saving a strategy file (`.py` in `src/strategies/`), the editor SHALL attempt to import the user strategy modules and instantiate a `PositionEngine` with them. If instantiation succeeds, "Engine OK" SHALL appear. If it fails, the error SHALL be displayed.

#### Scenario: Engine validates successfully
- **WHEN** the user saves a valid strategy file
- **THEN** the validation panel SHALL show "Engine OK" in green

#### Scenario: Engine validation fails
- **WHEN** the user saves a strategy that breaks PositionEngine instantiation
- **THEN** the validation panel SHALL show the exception type and message in red

#### Scenario: TOML file skips engine validation
- **WHEN** the user saves a `.toml` config file
- **THEN** engine validation SHALL be skipped (only syntax validation is skipped too; TOML is not Python)

### Requirement: Path security
All file operations SHALL validate the resolved absolute path against the `src/strategies/` allowlist only. `src/core/`, `src/bar_simulator/`, and all other directories SHALL be inaccessible. Path traversal attempts SHALL be rejected.

#### Scenario: Path traversal attempt rejected
- **WHEN** a callback receives a path like `src/strategies/../../core/types.py`
- **THEN** the operation SHALL return an error and no file I/O SHALL occur

#### Scenario: Core directory access blocked
- **WHEN** a callback receives `src/core/types.py`
- **THEN** the operation SHALL be rejected — core system files are not editable
