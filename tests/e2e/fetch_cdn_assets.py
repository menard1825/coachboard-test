"""Download the browser suite's vendored CDN files, pinned and verified.

    python tests/e2e/fetch_cdn_assets.py DIRECTORY

Fetches each exact versioned URL in cdn_assets.CDN_ASSETS, checks it against
cdn_assets.CDN_SHA256 and writes it to DIRECTORY under the name
require_vendored_assets() expects. Any download error or hash mismatch exits
non-zero and leaves nothing half-written; nothing falls back to anything.
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdn_assets import CDN_ASSETS, CDN_SHA256  # noqa: E402


def main(argv):
    if len(argv) != 2:
        raise SystemExit(__doc__)
    directory = Path(argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    assert set(CDN_SHA256) == {name for name, _ in CDN_ASSETS.values()}, 'every file needs a pinned hash'

    for path, (name, _) in CDN_ASSETS.items():
        url = f'https://{path}'
        with urllib.request.urlopen(url, timeout=60) as response:
            body = response.read()
        digest = hashlib.sha256(body).hexdigest()
        if digest != CDN_SHA256[name]:
            raise SystemExit(f'SHA-256 mismatch for {url}: got {digest}, expected {CDN_SHA256[name]}')
        partial = directory / f'{name}.partial'
        partial.write_bytes(body)
        partial.replace(directory / name)
        print(f'{name}: {len(body)} bytes, sha256 {digest} ok')


if __name__ == '__main__':
    main(sys.argv)
