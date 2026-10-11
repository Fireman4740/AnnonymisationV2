import json
import os
import uuid

def load_jsonl_data(file_path):
    """Load data from JSONL file"""
    data = []
    with open(file_path, 'r', encoding='utf-8') as file:
        for line in file:
            if line.strip():
                data.append(json.loads(line))
    return data

def save_jsonl_data(data, file_path):
    """Save data to JSONL file"""
    with open(file_path, 'w', encoding='utf-8') as file:
        for item in data:
            file.write(json.dumps(item, ensure_ascii=False) + '\n')

def generate_unique_uuids(n: int):
    uuids = set()
    while len(uuids) < n:
        uuids.add(str(uuid.uuid4())[:5])
    return list(uuids)