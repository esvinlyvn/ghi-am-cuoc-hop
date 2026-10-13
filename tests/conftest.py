"""Mọi bài kiểm thử dùng thư mục dữ liệu tạm; không chạm vào data/ thật của người dùng."""
import os
import sys
import tempfile
from pathlib import Path

os.environ['MEETING_DATA_DIR'] = tempfile.mkdtemp(prefix='meeting_scribe_tests_')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
