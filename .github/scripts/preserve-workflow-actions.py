"""Copy shared workflow logic while retaining repository-selected GitHub Actions.

Only actual job/step `uses` scalars are replaced, never examples in run strings.
Ambiguous references or unsupported YAML constructs fail before any write.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import tempfile

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, ScalarToken


class PolicyError(ValueError):
    """A safe workflow merge could not be established."""


@dataclass(frozen=True)
class Action:
    job: str
    identity: tuple[str, str]
    coordinate: str
    value: str
    start: int
    end: int
    comment: str
    line_end: int
    block_tail: bool


def mapping(node: yaml.Node, label: str) -> dict[str, yaml.Node]:
    if not isinstance(node, MappingNode):
        raise PolicyError(f"{label} must be a mapping")
    result = {}
    for key, value in node.value:
        if not isinstance(key, ScalarNode) or key.value in result or key.value == "<<":
            raise PolicyError(f"Duplicate, complex or merged key in {label}")
        result[key.value] = value
    return result


def validate_keys(node: yaml.Node, seen: set[int]) -> None:
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, MappingNode):
        for child in mapping(node, "workflow").values():
            validate_keys(child, seen)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            validate_keys(child, seen)


def actions(text: str) -> tuple[list[Action], bool]:
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is None:
        return [], False
    validate_keys(root, set())
    document = mapping(root, "workflow")
    tokens = list(yaml.scan(text, Loader=yaml.SafeLoader))
    anchored = any(isinstance(token, (AnchorToken, AliasToken)) for token in tokens)
    scalar_tokens = {token.end_mark.index: token for token in tokens if isinstance(token, ScalarToken)}
    result = []

    def add(job: str, identity: tuple[str, str], node: yaml.Node) -> None:
        if not isinstance(node, ScalarNode) or node.tag != "tag:yaml.org,2002:str":
            raise PolicyError("Action reference must be a string")
        if node.value.startswith(("./", "docker://")):
            return
        coordinate, separator, reference = node.value.partition("@")
        parts = coordinate.split("/")
        # Validate each segment once. Nested repetitions over slash-containing
        # character classes can take exponential time on malformed references.
        if (not separator or not reference or any(char.isspace() for char in reference)
                or len(parts) < 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts)):
            raise PolicyError("Unrecognized GitHub Action reference")
        token = scalar_tokens.get(node.end_mark.index)
        if token is None or token.style in ("|", ">") or token.start_mark.line != token.end_mark.line:
            raise PolicyError("Multiline Action references require manual review")
        end = token.end_mark.index
        line_end = text.find("\n", end)
        if line_end < 0:
            line_end = len(text)
        tail = text[end:line_end].rstrip("\r")
        block_tail = bool(re.fullmatch(r"[ \t]*(?:#[^\n]*)?", tail))
        comment = tail.strip() if block_tail else ""
        result.append(Action(job, identity, coordinate.lower(), node.value,
                             token.start_mark.index, end, comment, line_end, block_tail))

    if "jobs" not in document:
        return result, anchored
    for job, job_node in mapping(document["jobs"], "jobs").items():
        fields = mapping(job_node, "job")
        if "uses" in fields:
            add(job, ("job", job), fields["uses"])
        if "steps" not in fields:
            continue
        if not isinstance(fields["steps"], SequenceNode):
            raise PolicyError("steps must be a sequence")
        for step in fields["steps"].value:
            step_fields = mapping(step, "step")
            if "uses" not in step_fields:
                continue
            identity = ("anonymous", "")
            for key in ("id", "name"):
                if key in step_fields:
                    value = step_fields[key]
                    if not isinstance(value, ScalarNode):
                        raise PolicyError("Step identity must be scalar")
                    identity = (key, value.value)
                    break
            add(job, identity, step_fields["uses"])
    return result, anchored


def preserve(source: str, target: str) -> str:
    shared, shared_anchors = actions(source)
    owned, owned_anchors = actions(target)
    edits = []
    for action in shared:
        candidates = [old for old in owned if old.coordinate == action.coordinate]
        if not candidates:
            continue
        same_job = [old for old in candidates if old.job == action.job]
        if same_job:
            candidates = same_job
        if action.identity[0] != "anonymous":
            identified = [old for old in candidates if old.identity == action.identity]
            if identified:
                candidates = identified
        choices = {(old.value, old.comment) for old in candidates}
        if len(choices) != 1:
            raise PolicyError(f"Ambiguous existing references for {action.coordinate} in {action.job}")
        value, comment = choices.pop()
        if value == action.value and comment == action.comment:
            continue
        if shared_anchors or owned_anchors:
            raise PolicyError("Action changes in workflows with YAML anchors require manual review")
        # JSON strings are also valid YAML scalars. Preserve source quoting style
        # where possible without interpreting shell or workflow expressions.
        replacement = value
        if source[action.start] == '"':
            import json
            replacement = json.dumps(value)
        elif source[action.start] == "'":
            replacement = "'" + value.replace("'", "''") + "'"
        end = action.end
        if action.block_tail:
            end = action.line_end
            replacement += (" " + comment) if comment else ""
        elif comment:
            raise PolicyError("An annotated Action in flow YAML requires manual review")
        edits.append((action.start, end, replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    actions(source)
    return source


def copy_workflow(source: Path, target: Path) -> None:
    for path in (source, target):
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise PolicyError("Linked workflow paths are not supported")
        if path.exists() and not path.is_file():
            raise PolicyError("Workflow path is not a regular file")
    original = target.read_text(encoding="utf-8") if target.exists() else ""
    merged = preserve(source.read_text(encoding="utf-8"), original)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(merged)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3:
            raise PolicyError("Usage: preserve-workflow-actions.py SOURCE TARGET")
        copy_workflow(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"Workflow copy refused: {error}", file=sys.stderr)
        sys.exit(1)
