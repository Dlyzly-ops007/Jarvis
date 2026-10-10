"""Safe, bounded local-file searching for JARVIS."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Mapping


ALLOWED_CATEGORIES = ("Downloads", "Desktop", "Pictures", "Documents")


@dataclass(frozen=True)
class FileMatch:
    filename: str
    full_path: str
    location: str
    match_type: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class FileSearchResult:
    query: str
    matches: list[FileMatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_matches: int = 0

    @property
    def success(self) -> bool:
        return bool(self.matches)

    @property
    def message(self) -> str:
        if not self.query:
            return "No filename or search term was provided."
        if not self.matches:
            return f"No files matching '{self.query}' were found in the allowed folders."
        if self.total_matches == 1:
            return f"Found one file matching '{self.query}'."
        shown = len(self.matches)
        if shown < self.total_matches:
            return f"Found {self.total_matches} files matching '{self.query}' (showing {shown})."
        return f"Found {self.total_matches} files matching '{self.query}'."

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query,
            "matches": [match.as_dict() for match in self.matches],
            "errors": list(self.errors),
            "total_matches": self.total_matches,
            "success": self.success,
            "message": self.message,
        }

    def format_for_user(self) -> str:
        if not self.matches:
            return self.message
        lines = [self.message]
        for index, match in enumerate(self.matches, start=1):
            lines.append(f"{index}. {match.filename} [{match.location}]\n   {match.full_path}")
        return "\n".join(lines)


def default_search_roots(home: Path | None = None) -> dict[str, Path]:
    home_directory = home or Path.home()
    return {category: home_directory / category for category in ALLOWED_CATEGORIES}


def _match_rank(filename: str, query: str) -> tuple[int, str]:
    name = filename.casefold()
    stem = Path(filename).stem.casefold()
    term = query.casefold()
    if name == term:
        return 0, "exact_filename"
    if stem == term:
        return 1, "exact_stem"
    if name.startswith(term) or stem.startswith(term):
        return 2, "prefix"
    return 3, "partial"


def find_files(
    search_term: str,
    *,
    roots: Mapping[str, Path | str] | None = None,
    max_results: int = 50,
) -> FileSearchResult:
    """Recursively find files in the four explicitly allowed user folders.

    ``roots`` exists for testing and portable deployments. Its keys are the
    location/category returned to the caller; production callers should omit it.
    """

    query = " ".join((search_term or "").strip().strip('"\'').split())
    result = FileSearchResult(query=query)
    if not query:
        return result
    if max_results < 1:
        raise ValueError("max_results must be at least 1")

    search_roots = roots or default_search_roots()
    ranked_matches: list[tuple[int, str, FileMatch]] = []
    term = query.casefold()

    for category, raw_root in search_roots.items():
        root = Path(raw_root).expanduser()
        if not root.exists() or not root.is_dir():
            continue
        try:
            for current_directory, directory_names, filenames in os.walk(
                root, topdown=True, followlinks=False
            ):
                # Avoid recursive loops through directory symlinks/junction-like
                # entries while retaining normal nested-folder searching.
                directory_names[:] = [
                    name
                    for name in directory_names
                    if not (Path(current_directory) / name).is_symlink()
                ]
                for filename in filenames:
                    if term not in filename.casefold():
                        continue
                    full_path = Path(current_directory) / filename
                    rank, match_type = _match_rank(filename, query)
                    match = FileMatch(
                        filename=filename,
                        full_path=str(full_path.resolve()),
                        location=str(category),
                        match_type=match_type,
                    )
                    ranked_matches.append(
                        (rank, filename.casefold(), match)
                    )
        except (OSError, PermissionError) as exc:
            result.errors.append(f"{category}: {exc}")

    ranked_matches.sort(key=lambda item: (item[0], item[1], item[2].full_path.casefold()))
    result.total_matches = len(ranked_matches)
    result.matches = [item[2] for item in ranked_matches[:max_results]]
    return result


find_file = find_files

