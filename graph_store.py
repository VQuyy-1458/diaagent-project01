"""Import the delivered Cypher script and read the current graph through the shared adapter."""
import os
from pathlib import Path
from agents import graph

def statements(text):
    result = []
    current = []
    quote = None
    escaped = False
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        for char in line + "\n":
            if escaped:
                escaped = False
            elif quote and char == "\\":
                escaped = True
            elif char in ("\"", "'", "`"):
                if quote == char:
                    quote = None
                elif not quote:
                    quote = char
            if char == ";" and not quote:
                result.append("".join(current).strip())
                current = []
            else:
                current.append(char)
    if "".join(current).strip():
        result.append("".join(current).strip())
    return result

def load_graph(use_neo4j=True):
    if use_neo4j and os.getenv("NEO4J_URI"):
        from neo4j import GraphDatabase
        auth = (os.getenv("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]) if os.getenv("NEO4J_PASSWORD") else None
        with GraphDatabase.driver(os.environ["NEO4J_URI"], auth=auth, connection_timeout=5) as driver:
            script = Path(__file__).resolve().parent / "data/DB_diabet.cypher"
            for query in statements(script.read_text(encoding="utf8")):
                driver.execute_query(query, database_=os.getenv("NEO4J_DATABASE", "neo4j"))
    return graph(use_neo4j=use_neo4j)

