#!/usr/bin/env python3
"""
Script to truncate all data from the Knowledge Base (TinyDB).
"""
from pathlib import Path
from tinydb import TinyDB
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

# Path to the knowledge base
kb_path = Path("artifacts") / "knowledge_base.db.json"
if kb_path.exists():
    # Use without caching for truncation to ensure it's written
    from tinydb import TinyDB
    from tinydb.storages import JSONStorage
    db = TinyDB(str(kb_path), storage=JSONStorage, indent=2)
    print("Tables in Knowledge Base:", list(db.tables()))
    # Truncate all tables except app_profiles (assuming that's app data)
    for table_name in db.tables():
        if table_name != 'app_profiles':
            db.table(table_name).truncate()
    print("Knowledge Base truncated successfully, keeping app_profiles data.")
else:
    print("Knowledge Base file not found.")