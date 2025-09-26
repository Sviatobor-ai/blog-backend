import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise RuntimeError('DATABASE_URL is not set')
