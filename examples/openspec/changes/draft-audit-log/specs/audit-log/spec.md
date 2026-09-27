## ADDED Requirements

### Requirement: Audit log behaves well
The exporter SHALL record every export in `audit.log` and also rotate the log daily and also
be fast.

#### Scenario: Exports are audited
- **WHEN** an export runs
The log should look right afterwards.

### Scenario: The log rotates
- **WHEN** a day passes
- **THEN** the log rotates

### Requirement: Audit entries are readable
Entries SHALL be readable.
