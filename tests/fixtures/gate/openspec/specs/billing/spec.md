# billing Specification

## Purpose

Invoices are issued once per order and carry the order's total.

## Requirements

### Requirement: One invoice per order
The `invoice` command SHALL refuse a second invoice for the same order with exit code 4.

#### Scenario: A second invoice is refused
- **GIVEN** order 17 already has an invoice
- **WHEN** `invoice 17` runs
- **THEN** the command exits 4 and prints `already invoiced: 17`

### Requirement: Legacy export
The `invoice --csv` option SHALL write the invoice as CSV to standard output.

#### Scenario: CSV output
- **WHEN** `invoice 18 --csv` runs
- **THEN** standard output holds one CSV header line and one data line
