"""Collect installed licence notices and the exact PyOpenGL source-release notice.

Downloads source bytes for inspection only; never executes or extracts an archive.
"""

import argparse
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from importlib import metadata
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    inventory = {
        "scope": "installed runtime/dev, uv bootstrap, Python, cached build tools",
        "packages": [],
        "python_notices": [],
        "external_sources": [],
    }

    def preserve(name, filename, raw, source):
        target = args.output / name / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            file.write(raw)
        return {
            "path": str(target.relative_to(args.output)),
            "sha256": digest(raw),
            "source": source,
        }

    distributions = [("runtime-dev", d) for d in metadata.distributions()]
    bootstrap = root / ".tools/bootstrap/lib/python3.9/site-packages"
    distributions.extend(("bootstrap", d) for d in metadata.distributions(path=[str(bootstrap)]))
    build_names = {
        "hatchling",
        "packaging",
        "pathspec",
        "pluggy",
        "tomlkit",
        "trove-classifiers",
        "editables",
    }
    seen = set()
    for path in sorted((root / ".tools/uv-cache/archive-v0").glob("*/")):
        for dist in metadata.distributions(path=[str(path)]):
            key = dist.metadata["Name"].lower().replace("_", "-")
            if key in build_names and key not in seen:
                distributions.append(("build", dist))
                seen.add(key)
    for group, dist in distributions:
        name = dist.metadata["Name"]
        record = {
            "name": name,
            "version": dist.version,
            "group": group,
            "license_expression": dist.metadata.get("License-Expression"),
            "license": dist.metadata.get("License"),
            "license_classifiers": [
                c for c in dist.metadata.get_all("Classifier", []) if c.startswith("License ::")
            ],
            "notices": [],
        }
        for file in dist.files or []:
            filename = Path(str(file)).name
            if any(token in filename.lower() for token in ("license", "copying", "notice")):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    record["notices"].append(
                        preserve(
                            f"{group}-{name}",
                            f"{len(record['notices']):02}-{filename}",
                            source.read_bytes(),
                            str(file),
                        )
                    )
        inventory["packages"].append(record)

    python_notice = Path(sys.base_prefix) / "lib/python3.11/LICENSE.txt"
    inventory["python_notices"].append(
        preserve(
            "python", "LICENSE.txt", python_notice.read_bytes(), "installed CPython LICENSE.txt"
        )
    )

    # The installed 3.1.10 wheel omits its full licence. Inspect the exact PyPI sdist.
    version = metadata.version("PyOpenGL")
    metadata_url = f"https://pypi.org/pypi/PyOpenGL/{version}/json"
    with urllib.request.urlopen(metadata_url, timeout=30) as response:
        release_raw = response.read()
    preserve("pyopengl-release", "pypi.json", release_raw, metadata_url)
    release = json.loads(release_raw)
    sdist = next(file for file in release["urls"] if file["packagetype"] == "sdist")
    with urllib.request.urlopen(sdist["url"], timeout=30) as response:
        archive = response.read()
    if digest(archive) != sdist["digests"]["sha256"]:
        raise ValueError("PyOpenGL archive hash mismatch")
    entry = {"url": sdist["url"], "sha256": digest(archive), "notices": []}
    preserve("pyopengl-release", sdist["filename"], archive, sdist["url"])
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            if member.isfile() and any(
                t in Path(member.name).name.lower() for t in ("license", "copying", "notice")
            ):
                raw = tar.extractfile(member).read()
                entry["notices"].append(
                    preserve(
                        "pyopengl-source-notices",
                        f"{len(entry['notices']):02}-{Path(member.name).name}",
                        raw,
                        member.name,
                    )
                )
    if not entry["notices"]:
        raise ValueError("exact PyOpenGL source release has no licence notice")
    inventory["external_sources"].append(entry)
    (args.output / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(
        json.dumps(
            {
                "package_records": len(inventory["packages"]),
                "pyopengl_source_notices": len(entry["notices"]),
                "source_sha256": entry["sha256"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
