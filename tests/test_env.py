import os
from pathlib import Path


def test_dotenv_dependency_declared():
    text = Path('pyproject.toml').read_text(encoding='utf-8')
    assert 'python-dotenv' in text
