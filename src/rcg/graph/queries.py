"""Cypher templates. Kept in one place so the schema is easy to audit."""

MERGE_RULE_FILE = """
MERGE (f:RuleFile {path: $path})
SET f.format = $format
"""

MERGE_RULE = """
MERGE (r:Rule {id: $id})
SET r.raw_text = $raw_text,
    r.action = $action,
    r.action_class = $action_class,
    r.scope_pattern = $scope_pattern,
    r.modality = $modality,
    r.confidence = $confidence,
    r.original_language = $original_language,
    r.tags = $tags,
    r.line_start = $line_start,
    r.line_end = $line_end,
    r.section = $section
WITH r
MATCH (f:RuleFile {path: $file})
MERGE (r)-[:DERIVED_FROM]->(f)
"""

MERGE_CONFLICT = """
MATCH (a:Rule {id: $a_id}), (b:Rule {id: $b_id})
MERGE (a)-[c:CONFLICTS_WITH {type: $type}]-(b)
SET c.severity = $severity,
    c.reason = $reason
"""

COUNT_RULES = "MATCH (r:Rule) RETURN count(r) AS n"
COUNT_CONFLICTS = "MATCH ()-[c:CONFLICTS_WITH]->() RETURN count(c) AS n"

# Count every node in the graph (used by the public-demo node cap).
COUNT_NODES = "MATCH (n) RETURN count(n) AS n"

# Delete every node and relationship (used to auto-clear the demo graph at cap).
CLEAR_ALL = "MATCH (n) DETACH DELETE n"
