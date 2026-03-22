## MODIFIED Requirements

### Requirement: File browser sidebar
The Strategy > Code Editor sub-tab sidebar SHALL list all editable files under `src/strategies/` as a grouped flat list. Files SHALL be grouped by subdirectory (root, configs/). The currently selected file SHALL be visually highlighted. This behavior is identical to the previous top-level Strategy tab — only the navigation path changes.

#### Scenario: File list populates on sub-tab load
- **WHEN** the user navigates to Strategy > Code Editor
- **THEN** the sidebar SHALL display all Python and TOML files from `src/strategies/` grouped by directory

#### Scenario: Editor state preserved across sub-tab switches
- **WHEN** the user switches from Code Editor to Optimizer and back
- **THEN** the editor SHALL preserve the last selected file and cursor position via dcc.Store
