from tinydb import TinyDB
db = TinyDB('python_agent/artifacts/knowledge_base.db.json')
for table in db.tables():
    print(table, db.table(table).all())
db.close()