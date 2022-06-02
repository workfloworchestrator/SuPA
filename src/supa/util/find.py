#  Copyright 2020 SURF.
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
"""Utilities to find files and directories."""
import errno
from pathlib import Path
from sys import path
from typing import Union


def find_file(pathname: Union[str, Path]) -> Path:
    """Find file 'pathname' along sys.path."""
    for directory in path:
        if (candidate := Path(directory) / pathname).is_file():
            return candidate
    raise FileNotFoundError(
        errno.ENOENT,
        f"Could not find '{pathname}' file on sys.path.",
        path,
    )


def find_directory(pathname: Union[str, Path]) -> Path:
    """Find directory 'pathname' along sys.path."""
    for directory in path:
        if (candidate := Path(directory) / pathname).is_dir():
            return candidate
    raise FileNotFoundError(
        errno.ENOENT,
        f"Could not find '{pathname}' file on sys.path.",
        path,
    )
