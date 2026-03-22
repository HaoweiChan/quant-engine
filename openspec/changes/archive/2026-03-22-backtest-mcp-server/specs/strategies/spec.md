## ADDED Requirements

### Requirement: Strategy file validation
The system SHALL provide a validation function that checks strategy file content before it is written to `src/strategies/`.

```python
@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]

def validate_strategy_content(content: str, filename: str) -> ValidationResult: ...
```

#### Scenario: Syntax validation
- **WHEN** `validate_strategy_content` is called with content containing a Python syntax error
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include the syntax error message with line number

#### Scenario: Forbidden import detection
- **WHEN** content contains `import os`, `import sys`, `import subprocess`, `import socket`, `import requests`, or `import shutil`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include `"Forbidden import: <module>"`

#### Scenario: Forbidden from-import detection
- **WHEN** content contains `from os import ...` or `from subprocess import ...`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL include `"Forbidden import: <module>"`

#### Scenario: Policy ABC interface check
- **WHEN** content defines a class that subclasses `EntryPolicy`, `AddPolicy`, or `StopPolicy`
- **THEN** validation SHALL verify the class implements all required abstract methods of that ABC

#### Scenario: Missing method detected
- **WHEN** a class subclasses `StopPolicy` but does not define `initial_stop` or `update_stop`
- **THEN** `ValidationResult.valid` SHALL be `False` and `errors` SHALL list the missing methods

#### Scenario: Valid content passes
- **WHEN** content is syntactically valid Python, contains no forbidden imports, and all policy classes implement required methods
- **THEN** `ValidationResult.valid` SHALL be `True` and `errors` SHALL be empty

### Requirement: Strategy file backup
The system SHALL provide a backup mechanism for strategy files before they are overwritten.

```python
def backup_strategy_file(filename: str) -> str | None: ...
```

#### Scenario: Backup before overwrite
- **WHEN** `backup_strategy_file` is called for an existing file
- **THEN** it SHALL copy the current file to `src/strategies/.backup/<filename>.<ISO-timestamp>.py` and return the backup path

#### Scenario: Backup directory creation
- **WHEN** `src/strategies/.backup/` does not exist
- **THEN** `backup_strategy_file` SHALL create it before saving the backup

#### Scenario: No backup for new files
- **WHEN** `backup_strategy_file` is called for a filename that does not exist in `src/strategies/`
- **THEN** it SHALL return `None` without creating a backup

### Requirement: Strategy file listing
The system SHALL provide a function to list available strategy files.

```python
def list_strategy_files() -> list[dict]: ...
```

#### Scenario: List all strategy files
- **WHEN** `list_strategy_files` is called
- **THEN** it SHALL return a list of `{"filename": str, "size_bytes": int, "modified": str}` for each `.py` file in `src/strategies/` (excluding `__init__.py` and `__pycache__/`)

#### Scenario: Empty strategies directory
- **WHEN** `src/strategies/` contains no `.py` files (other than `__init__.py`)
- **THEN** it SHALL return an empty list
