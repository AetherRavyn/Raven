import asyncio
import json
import urllib.request
from urllib.error import URLError

def check_server():
    try:
        req = urllib.request.Request("http://localhost:8090/")
        with urllib.request.urlopen(req) as response:
            return response.status == 200
    except URLError:
        return False

print(f"Server accessible: {check_server()}")
