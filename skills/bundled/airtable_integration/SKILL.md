---
name: Airtable Integration
module_id: skill.bundled.airtable_integration
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "airtable.*record|airtable.*table"
    confidence: 0.90
  - pattern: "list.*airtable|airtable.*data"
    confidence: 0.85
capabilities: [airtable, database, spreadsheet]
trust_level: user_config
enabled_by_default: false
stability: stable
---

# Airtable Integration

Read and write records in Airtable bases via the Airtable REST API.

## Procedure

### List Records
- Call `airtable` with `action=list_records`, `base_id=<id>`, `table_id=<id>`

### Get Record
- Call `airtable` with `action=get_record`, `base_id=<id>`, `table_id=<id>`, `record_id=<id>`

### Create Record
- Call `airtable` with `action=create_record`, `base_id=<id>`, `table_id=<id>`, `fields=<dict>`

### Update Record
- Call `airtable` with `action=update_record`, `base_id=<id>`, `table_id=<id>`, `record_id=<id>`, `fields=<dict>`

### Delete Record
- Call `airtable` with `action=delete_record`, `base_id=<id>`, `table_id=<id>`, `record_id=<id>`

## Configuration
Requires `AIRTABLE_API_KEY` environment variable.
