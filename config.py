# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.environ.get("TURSO_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "")

LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "123456")

SECRET_KEY = os.environ.get("SECRET_KEY", "lhc-web-secret-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_PATH = os.path.join(DATA_DIR, "draws.csv")

# 状态加权参数
TAIL_W = (0.85, 1.00, 1.15, 0.95)

ODDS = 46