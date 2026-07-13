from __future__ import annotations

import asyncio
import os
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from queue import SimpleQueue
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Web