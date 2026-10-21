import os
from pathlib import Path
from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent.parent if PACKAGE_DIR.parent.name == 'src' else Path.cwd()
load_dotenv(ROOT / '.env')
DATABASE_URL = os.getenv('DATABASE_URL', '')
POD_URL = os.getenv('SCIENCE_AGENT_POD_URL', '')
POD_TIMEOUT = int(os.getenv('SCIENCE_AGENT_POD_TIMEOUT', '900'))
UPLOAD_LIMIT = int(os.getenv('UPLOAD_LIMIT', str(64 * 1024 * 1024)))
# Used only by the one-time local-file import command.
LEGACY_UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', str(ROOT / 'uploads'))).resolve()
TAPIS_BASE_URL = os.getenv('TAPIS_BASE_URL', 'https://icicleai.tapis.io')
TAPIS_ALLOWED_TENANTS = set(os.getenv('TAPIS_ALLOWED_TENANTS', 'icicleai').split(','))
FRONTEND_ORIGINS = set(os.getenv('FRONTEND_ORIGINS', 'http://127.0.0.1:5173,http://localhost:5173').split(','))
SMART_LABELER_BASE_URL = os.getenv('SMART_LABELER_BASE_URL', 'https://smartlabelerbackend.pods.icicleai.tapis.io')
SKILLS_DIR = PACKAGE_DIR / 'skills'
