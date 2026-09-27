## MODIFIED Requirements

### Requirement: One invoice per order
The `invoice` command SHALL refuse a second invoice for the same order with exit code 4 and
leave the first invoice unchanged.

#### Scenario: A second invoice is refused
- **GIVEN** order 17 already has an invoice
- **WHEN** `invoice 17` runs
- **THEN** the command exits 4 and prints `already invoiced: 17`
- **AND** the first invoice file is byte-identical to before

## ADDED Requirements

### Requirement: Invoice totals are rounded to cents
The `invoice` command SHALL print totals rounded half up to two decimal places.

#### Scenario: A total of 10.005 is printed as 10.01
- **GIVEN** order 19 whose line items sum to 10.005
- **WHEN** `invoice 19` runs
- **THEN** the printed total is `10.01`

## REMOVED Requirements

### Requirement: Legacy export
**Reason**: CSV output moved to the `report` command.
**Migration**: use `report --csv`.
