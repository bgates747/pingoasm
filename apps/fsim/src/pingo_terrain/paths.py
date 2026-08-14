"""Stable project paths shared by terrain tools and tests."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
DOWNLOAD_ROOT = DATA_ROOT / "downloads"
MANIFEST_ROOT = DATA_ROOT / "manifests"
FIXTURE_ROOT = PROJECT_ROOT / "fixtures"
PROFILE_ROOT = PROJECT_ROOT / "profiles"
BUILD_ROOT = PROJECT_ROOT / "build"
