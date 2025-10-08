#
# Copyright 2019 Delphix
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
Version information for sdb
"""

import os
import subprocess
from typing import Optional


def get_git_commit_hash() -> Optional[str]:
    """
    Get the current git commit hash.
    Returns None if not in a git repository or git is not available.
    """
    try:
        # Get the directory where this module is located
        module_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up one level to get to the repository root (sdb/ -> repo_root/)
        repo_root = os.path.dirname(module_dir)
        
        # Run git rev-parse to get the current commit hash
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def get_version() -> str:
    """
    Get the version string for sdb.
    Uses git commit hash if available, otherwise falls back to package version.
    """
    commit_hash = get_git_commit_hash()
    if commit_hash:
        # Use short hash for readability
        return f"sdb-{commit_hash[:8]}"
    
    # Fallback to package version if git is not available
    return "sdb-0.1.0"