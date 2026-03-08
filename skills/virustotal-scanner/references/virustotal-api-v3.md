# VirusTotal API v3 Quick Reference

Base URL:
- `https://www.virustotal.com/api/v3`

Auth:
- Header: `x-apikey: <your_api_key>`

Common endpoints used by this project:
- `POST /urls` -> submit URL for scanning
- `GET /urls/{url_id}` -> URL report
- `GET /files/{hash}` -> file report by hash
- `GET /domains/{domain}` -> domain report
- `GET /ip_addresses/{ip}` -> IP report
- `GET /analyses/{id}` -> analysis status/result
- `POST /files` -> upload file (standard upload path)

URL ID:
- URL report endpoint uses a URL-safe base64-encoded URL identifier.
- Remove trailing `=` padding from base64 output.

Interpretation:
- Use `data.attributes.last_analysis_stats` where available.
- Important fields: `malicious`, `suspicious`, `harmless`, `undetected`.
- Treat high `undetected` as uncertain coverage, not a clean guarantee.
