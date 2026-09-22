#!/usr/bin/env python3
"""Check the repository's Codex discovery paths and maintained source files."""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

try:
    import tomllib
except ModuleNotFoundError:
    raise SystemExit("Python 3.11 or later is required.")


def unfenced(text):
    marker = None
    for line in text.splitlines():
        fence = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            token, rest = fence.groups()
            if marker is None:
                marker = token
            elif token[0] == marker[0] and len(token) >= len(marker) and not rest.strip():
                marker = None
            continue
        if marker is None:
            yield line


def check(root):
    errors = []

    def require(condition, message):
        if not condition:
            errors.append(message)

    manifest = root / "codex/skills.list"
    managed_skills = []
    if manifest.is_file():
        managed_skills = [line.strip() for line in manifest.read_text(encoding="utf-8").splitlines()
                          if line.strip() and not line.lstrip().startswith("#")]
    require(bool(managed_skills), "codex/skills.list: no managed skills")
    require(len(managed_skills) == len(set(managed_skills)), "codex/skills.list: duplicate skill")
    for name in managed_skills:
        require(bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)), f"Invalid managed skill: {name}")
    connections = [(".codex/agents", "codex/agents")]
    connections.extend((f".agents/skills/{name}", f"shared/skills/{name}") for name in managed_skills)
    require(not (root / ".agents/skills").is_symlink(), ".agents/skills: broad directory link exposes unrelated skills; run the installer")
    for native, source in connections:
        path = root / native
        try:
            connected = path.is_dir() and path.resolve() == (root / source).resolve()
        except (OSError, RuntimeError):
            connected = False
        require(connected, f"{native}: missing or incorrect connection; run bash scripts/install-codex.sh")

    def read_toml(path):
        try:
            return tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            return {}

    config = read_toml(root / ".codex/config.toml")
    agents_config = config.get("agents", {})
    require(agents_config.get("enabled") is True, ".codex/config.toml: agents.enabled must be true")
    limit = agents_config.get("max_concurrent_threads_per_session")
    require(type(limit) is int and limit > 0, ".codex/config.toml: concurrency limit must be a positive integer")

    agents = sorted((root / "codex/agents").glob("*.toml"))
    require(bool(agents), "No custom agent definitions found")
    names = set()
    for path in agents:
        data = read_toml(path)
        for key in ("name", "description", "developer_instructions"):
            require(isinstance(data.get(key), str) and bool(data[key].strip()), f"{path.name}: missing {key}")
        name = data.get("name")
        if isinstance(name, str):
            require(name == path.stem, f"{path.name}: name differs from filename")
            require(name not in names, f"Duplicate agent name: {name}")
            names.add(name)
        instructions = data.get("developer_instructions", "")
        if isinstance(instructions, str):
            for ref in re.findall(r"shared/skills/[a-z0-9-]+/SKILL\.md", instructions):
                require((root / ref).is_file(), f"{path.name}: missing skill {ref}")

    skills = [root / "shared/skills" / name / "SKILL.md" for name in managed_skills]
    require(bool(skills), "No skills found")
    skill_names = set()
    for path in skills:
        if not path.is_file():
            errors.append(f"Missing skill: {path.relative_to(root)}")
            continue
        text = path.read_text(encoding="utf-8")
        frontmatter = re.match(r"\A---\n(.*?)\n---(?:\n|$)", text, re.S)
        if not frontmatter:
            errors.append(f"{path.relative_to(root)}: missing YAML frontmatter")
            continue
        # These skills intentionally use only plain, single-line name/description fields.
        fields = dict(re.findall(r"^(name|description):\s*(\S[^\n]*)$", frontmatter[1], re.M))
        name = fields.get("name", "")
        require(bool(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)), f"{path.parent.name}: invalid skill name")
        require(name == path.parent.name, f"{path.parent.name}: skill name differs from folder")
        require(name not in skill_names, f"Duplicate skill name: {name}")
        skill_names.add(name)
        require(bool(fields.get("description")), f"{path.parent.name}: missing description")

    documents = [root / "AGENTS.md", root / "README.md"]
    for directory in ("codex", "orchestration", "templates/book"):
        documents.extend(sorted((root / directory).rglob("*.md")))
    documents.extend(skills)
    documents.extend(root / "shared/instructions" / name for name in ("project-guide.md", "book-contract.md"))
    for path in documents:
        if not path.is_file():
            errors.append(f"Missing document: {path.relative_to(root)}")
            continue
        for line in unfenced(path.read_text(encoding="utf-8")):
            for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", line):
                parts = urlsplit(target.strip("<>"))
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                destination = path.parent / unquote(parts.path)
                require(destination.exists(), f"{path.relative_to(root)}: broken local link {target}")

    if errors:
        for message in errors:
            print(f"FAIL: {message}", file=sys.stderr)
        return 1
    print(f"OK: discovery connections, config, {len(agents)} agents, {len(skills)} skills, {len(documents)} documents")
    print("Static checks only; runtime discovery and editorial quality need separate verification.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    return check(args.root.resolve())


if __name__ == "__main__":
    sys.exit(main())
