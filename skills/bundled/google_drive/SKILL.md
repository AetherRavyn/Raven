---
name: Google Drive
module_id: skill.bundled.google_drive
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "list.*drive.*file|google.*drive"
    confidence: 0.90
  - pattern: "upload.*drive|download.*drive|drive.*folder"
    confidence: 0.85
capabilities: [google-drive, cloud-storage]
trust_level: user_config
enabled_by_default: false
stability: stable
---

# Google Drive Integration

List, upload, download, and search files in Google Drive.

## Procedure

### List Files
- Call `google_drive` with `action=list_files`, optional `folder_id` and `page_size`

### Upload File
- Call `google_drive` with `action=upload_file`, `local_path=<path>`, optional `mime_type` and `parent_folder_id`

### Download File
- Call `google_drive` with `action=download_file`, `file_id=<id>`, `local_path=<path>`

### Search Files
- Call `google_drive` with `action=search`, `query=<text>` to find files by name/content

### Create Folder
- Call `google_drive` with `action=create_folder`, `name=<name>`, optional `parent_folder_id`

## Configuration
Uses Google OAuth (same credentials.json pattern as Docs/Sheets tools).
