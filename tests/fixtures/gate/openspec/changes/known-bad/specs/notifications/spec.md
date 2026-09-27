# Delta for notifications

## ADDED Requirements

### Requirement: Notifications work
The service SHALL send notifications and also retry failures and also be fast.

#### Scenario: Notification is sent
- **GIVEN** an invoice
The message should look right.
- **THEN** a message is sent

### Scenario: Retry happens
- **WHEN** the mail endpoint fails
- **THEN** the service retries

#### Scenario: Empty step
- **WHEN**
- **THEN** nothing happens

### Requirement - missing colon
The service SHALL log every message.

#### Scenario: Orphaned by the malformed heading above
- **WHEN** a message is sent
- **THEN** it is logged

### Requirement: No scenario at all
The service SHALL keep a copy of every message for 30 days.
