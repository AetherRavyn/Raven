---
name: virustotal-scanner
description: Use this skill when the user wants malware/reputation checks for URLs, domains, IPs, or file hashes/files using VirusTotal API v3; includes IOC extraction, safe scan workflow, and result interpretation.
---

# VirusTotal Scanner Skill

Use this skill for security reputation checks and malware scanning requests.

## Trigger Conditions

Use this skill when user asks to:
- scan a URL/domain/IP/hash for malware
- check if a file/hash is malicious
- run VirusTotal checks or VT lookups
- validate suspicious indicators before taking action

## Workflow

1. Extract indicator type from the user input:
- URL (`http://` or `https://`)
- File hash (md5/sha1/sha256)
- Domain
- IPv4/IPv6
- File path (if local file scanning requested)

2. Choose the lowest-risk tool operation:
- Passive lookup first:
  - `get_url_report`
  - `get_file_report`
  - `get_domain_report`
  - `get_ip_report`
- Active scan only when needed:
  - `scan_url`
  - `upload_file`
  - `scan_and_wait_url`
  - `scan_and_wait_file`

3. Interpret verdict from `last_analysis_stats`:
- `malicious > 0`: treat as high risk
- `suspicious > 0` with low malicious: caution
- high `undetected` with low coverage: inconclusive

4. Reply format:
- What was checked
- Detection summary (`malicious/suspicious/harmless/undetected`)
- Clear action recommendation (block, monitor, or allow with caution)

## Safety Notes

- Never claim a clean verdict means guaranteed safe.
- Flag low-coverage or stale results as inconclusive.
- Do not execute unknown files; this skill is for reputation checks, not sandbox execution.

## References

- For endpoint mapping and operation guidance, see `references/virustotal-api-v3.md`.
