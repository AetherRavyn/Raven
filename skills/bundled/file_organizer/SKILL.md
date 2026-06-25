---
name: File Organizer
module_id: skill.bundled.file_organizer
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "organize.*file"
    confidence: 0.90
  - pattern: "clean.*directory"
    confidence: 0.85
  - pattern: "sort.*download"
    confidence: 0.80
  - pattern: "declutter"
    confidence: 0.70
capabilities: [file-sorting, directory-cleaning, file-categorization, duplicate-detection]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# File Organizer

Organize files in a directory by type, date, or custom rules.

## When to Use
This skill activates when the user wants to clean up a messy directory (Downloads, Desktop, project folder). It categorizes files, creates organized subdirectories, and optionally removes duplicates.

## Procedure

### Step 1: Scan Directory
1. Call `FileTool.list_directory` on the target path
2. Get file count, total size, and list of all files
3. Identify file types by extension: images, documents, code, archives, etc.
4. Report current state before making changes

### Step 2: Propose Organization Plan
Group files into categories:
```
📁 Images/        — .jpg, .png, .gif, .svg, .webp
📁 Documents/     — .pdf, .docx, .txt, .md, .csv
📁 Code/          — .py, .js, .ts, .go, .rs, .java
📁 Archives/      — .zip, .tar.gz, .rar, .7z
📁 Data/          — .json, .yaml, .xml, .sql
📁 Media/         — .mp4, .mp3, .wav, .mov
📁 Other/         — everything else
```
Or by date: `YYYY/MM/` structure based on file modification time.

### Step 3: Execute Organization
1. Create target directories if they don't exist
2. Move files into appropriate directories
3. Rename any files with ambiguous or generic names (e.g., `untitled.txt` → `2026-06-22_notes.txt`)

### Step 4: Post-Cleanup
1. Check for duplicate files (same name + size) and flag them
2. Remove empty directories
3. Report summary of changes made

## Example

**Input:** `organize my Downloads folder`

**Output:**
```
📂 Downloads — 47 files, 2.3 GB

📊 Categories found:
  • 15 images (320 MB)
  • 12 documents (45 MB)
  • 8 archives (1.8 GB)
  • 6 code files (12 KB)
  • 4 data files (28 MB)
  • 2 media files (95 MB)

✅ Organized into:
  📁 Images/ → 15 files
  📁 Documents/ → 12 files
  📁 Archives/ → 8 files
  📁 Code/ → 6 files
  📁 Data/ → 4 files
  📁 Media/ → 2 files

🔍 Found 2 potential duplicates:
  • report-v2.pdf and report-final.pdf (same size)
  • photo(1).jpg and photo.jpg (same size)

Recommendation: Review duplicates and delete old versions.
```

## Lessons Learned
- Never delete files without explicit user confirmation
- Use `shutil.move` not `shutil.copy` to avoid doubling disk usage
- Symlinks need special care — don't follow or move them blindly
- Always preview the plan before executing destructive moves
- Large files (videos, ISOs) deserve separate attention
