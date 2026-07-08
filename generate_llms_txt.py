import os

DOCS_DIR = "/home/swadhin/SARAS/docs"
PUBLIC_DIR = "/home/swadhin/SARAS/site/public"

# Ensure public dir exists
os.makedirs(PUBLIC_DIR, exist_ok=True)

# Define the order of files based on Nav
FILES = [
    "overview.md",
    "installation.md",
    "deployment.md",
    "features-core.md",
    "features-tool-gateway.md",
    "features-automation.md",
    "features-media-web.md",
    "features-skills.md",
    "features-voice.md",
    "features-sensors.md",
    "features-safety.md",
    "messaging-platforms.md",
    "integrations.md",
    "guides-agents.md",
    "guides-soul.md",
    "developer-architecture.md",
    "developer-repo-structure.md",
    "roadmap-gaps.md",
    "reference-cli.md",
]

llms_txt_content = """# RAVEN Documentation Index

This is a machine-readable index of the RAVEN advanced user manual.
RAVEN is a JARVIS-class personal AI agent and intelligent orchestration system.

## Available Documentation

"""

llms_full_content = """# RAVEN Advanced User Manual (Full)

This file contains the complete, concatenated documentation for the RAVEN ecosystem.

"""

for filename in FILES:
    filepath = os.path.join(DOCS_DIR, filename)
    if not os.path.exists(filepath):
        continue
        
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Get the title (first # heading)
    title = filename
    for line in content.split('\n'):
        if line.startswith('# '):
            title = line.replace('# ', '').strip()
            break
            
    # Append to llms.txt index
    slug = filename.replace('.md', '')
    llms_txt_content += f"- [{title}](/{slug}/)\n"
    
    # Append to llms-full.txt
    llms_full_content += f"\n\n{'='*80}\n"
    llms_full_content += f"### {title}\n"
    llms_full_content += f"Path: /{slug}/\n"
    llms_full_content += f"{'='*80}\n\n"
    llms_full_content += content

with open(os.path.join(PUBLIC_DIR, "llms.txt"), "w", encoding="utf-8") as f:
    f.write(llms_txt_content)
    
with open(os.path.join(PUBLIC_DIR, "llms-full.txt"), "w", encoding="utf-8") as f:
    f.write(llms_full_content)

print("Successfully generated llms.txt and llms-full.txt in site/public/")
