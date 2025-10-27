"""
Project-based storage helpers.

Layout:
    <DATA_ROOT>/<username>/<project_slug>/{clips,intros,outros,transitions,compilations}
    Thumbnails: <DATA_ROOT>/<username>/_thumbnails
    Library (shared, reusable): <DATA_ROOT>/<username>/_library/{intros,outros,transitions,images,clips}

DATA_FOLDER may be an absolute or relative path. If relative, it's resolved under app.instance_path.
"""
from __future__ import annotations

import os
import re

from flask import current_app


def data_root() -> str:
    # Resolve data root for project layout; default to instance/data
    try:
        base = current_app.config.get("DATA_FOLDER") or "data"
        if os.path.isabs(base):
            return base
        return os.path.join(current_app.instance_path, base)
    except Exception:
        return os.path.join(os.getcwd(), "instance", "data")


def slugify(s: str | None) -> str:
    s = (s or "").strip()
    s = s.replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("._-") or "untitled"


def username_of(user) -> str:
    try:
        return slugify(getattr(user, "username", None) or f"user_{user.id}")
    except Exception:
        return "user"


def user_root(user) -> str:
    return os.path.join(data_root(), username_of(user))


def project_root(user, project_name: str | None) -> str:
    slug = slugify(project_name or "project")
    return os.path.join(user_root(user), slug)


def library_root(user) -> str:
    return os.path.join(user_root(user), "_library")


def thumbnails_dir(user) -> str:
    return os.path.join(user_root(user), "_thumbnails")


def clips_dir(user, project_name: str | None) -> str:
    root = project_root(user, project_name)
    return os.path.join(root, "clips")


def intros_dir(user, project_name: str | None = None, library: bool = False) -> str:
    root = library_root(user) if library else project_root(user, project_name)
    return os.path.join(root, "intros")


def outros_dir(user, project_name: str | None = None, library: bool = False) -> str:
    root = library_root(user) if library else project_root(user, project_name)
    return os.path.join(root, "outros")


def transitions_dir(
    user, project_name: str | None = None, library: bool = False
) -> str:
    root = library_root(user) if library else project_root(user, project_name)
    return os.path.join(root, "transitions")


def compilations_dir(user, project_name: str | None) -> str:
    root = project_root(user, project_name)
    return os.path.join(root, "compilations")


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        try:
            os.makedirs(p, exist_ok=True)
        except Exception:
            pass


def instance_canonicalize(path: str | None) -> str | None:
    """Convert an absolute path under the app's instance_path into a canonical
    '/instance/<suffix>' form for storage in the database or logs.

    If the path is already in '/instance/...' form, it is returned unchanged.
    If the path does not reside under instance_path or any error occurs,
    the original path is returned.
    """
    if not path:
        return path
    try:
        # Already canonical
        if str(path).startswith("/instance/"):
            return path
        base = current_app.instance_path  # type: ignore[attr-defined]
        pabs = os.path.abspath(str(path))
        baseabs = os.path.abspath(str(base))
        # Compute relative; if outside base, rel will start with '..'
        rel = os.path.relpath(pabs, baseabs)
        if not rel.startswith(".."):
            rel = rel.lstrip("./")
            return "/instance/" + rel.replace("\\", "/")
    except Exception:
        # Fall back to original on any error
        return path
    return path
