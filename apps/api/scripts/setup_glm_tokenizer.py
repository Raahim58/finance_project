"""Install pinned data-only tokenizer assets; no weights or remote code."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "storage/tokenizers/glm45"
REVISION = "a24ceef6ce4f3536971efe9b778bdaa1bab18daa"
FILES = {
    "tokenizer.json": "9340665016419c825c4bdabbcc9acc43b7ca2c68ce142724afa829abb1be5efd",
    "chat_template.jinja": "44f815868bf02fa458dd2f741a338046f4bf45f398eb6d067766726b9d96cce3",
}
ROOT.mkdir(parents=True, exist_ok=True)
for name, digest in FILES.items():
    target = ROOT / name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
        continue
    url = f"https://huggingface.co/zai-org/GLM-4.5-Air/resolve/{REVISION}/{name}"
    with urlopen(url, timeout=60) as response:
        content = response.read(25_000_001)
    if len(content) > 25_000_000 or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"Invalid pinned tokenizer asset: {name}")
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(target)
print(f"Tokenizer assets ready: {ROOT}")
