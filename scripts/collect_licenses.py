"""Collect installed distribution license texts into a local build directory."""
import importlib.metadata
import re
import shutil
import sys
from pathlib import Path


def main():
    output = Path(sys.argv[1])
    target = output / "THIRD_PARTY_LICENSES"
    count = 0
    for distribution in importlib.metadata.distributions():
        name = re.sub(r"[^a-zA-Z0-9._-]", "_", distribution.metadata["Name"])
        version = re.sub(r"[^a-zA-Z0-9._-]", "_", distribution.version)
        for relative in distribution.files or []:
            path = Path(str(relative))
            text_file = path.suffix.lower() in {"", ".txt", ".md", ".rst", ".html"}
            license_path = any("license" in part.lower() or part.lower().startswith("copying") for part in path.parts)
            if text_file and license_path and ".." not in path.parts:
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    destination = target / f"{name}-{version}" / path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)
                    count += 1
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(python_license, target / "PYTHON-LICENSE.txt")
    shutil.copyfile("LICENSE", output / "LICENSE.txt")
    shutil.copyfile("docs/THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    print(f"Collected {count} installed-distribution license texts; final release audit still required.")


if __name__ == "__main__":
    main()
