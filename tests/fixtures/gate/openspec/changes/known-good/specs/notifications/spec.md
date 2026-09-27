# Delta for notifications

## Purpose

Customers are told by email when an invoice is issued.

## ADDED Requirements

### Requirement: Issued invoices send one notification
The service SHALL send exactly one notification per issued invoice to the order's contact.

#### Scenario: Issuing an invoice sends one notification
- **GIVEN** a fake mail endpoint that records outbound messages
- **WHEN** `invoice 21` runs
- **THEN** the fake endpoint has recorded exactly one message for order 21
