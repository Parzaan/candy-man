"""
Step 0: Repo Loader
Clones GitHub URL or reads local path, walks all .py files, parses ASTs with per-file try/except,
and returns (list_of_asts, unscannable_files).
"""
from typing import List, Tuple, Any

def load_repository(target: str, target_type: str) -> Tuple[List[Any], List[str]]:
    """
    Accepts target path/URL and type ('local' | 'github').
    Returns a tuple of (parsed_file_objects, unscannable_files).
    """
    # TODO: Implement step 0 logic
    return [], []
