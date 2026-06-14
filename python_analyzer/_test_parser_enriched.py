"""
Verify the enriched parser produces correct binding, called_names, is_dead_import
on a small synthetic registry with two files.
"""
import sys, os, tempfile, json
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from modules.parser import parse_codebase

# ---------------------------------------------------------------------------
# Create a tiny temporary repo with two files
# ---------------------------------------------------------------------------
repo_dir = tempfile.mkdtemp(prefix="codesight_test_")

src_dir = Path(repo_dir) / "src"
(src_dir / "controllers").mkdir(parents=True)
(src_dir / "services").mkdir(parents=True)
(src_dir / "config").mkdir(parents=True)

# studentController.js — imports service (used) and logger (dead)
(src_dir / "controllers" / "studentController.js").write_text("""
const studentService = require('../services/studentService');
const logger = require('../config/logger');

exports.getAll = async (req, res) => {
    const students = await studentService.findAll(req.query);
    res.json(students);
};

exports.getById = async (req, res) => {
    const student = await studentService.findById(req.params.id);
    res.json(student);
};
""")

# studentService.js — exports findAll and findById
(src_dir / "services" / "studentService.js").write_text("""
const findAll = async (query) => {
    return [];
};
const findById = async (id) => {
    return null;
};
module.exports = { findAll, findById };
""")

# logger.js — imported by controller but never called
(src_dir / "config" / "logger.js").write_text("""
const winston = require('winston');
module.exports = winston.createLogger({});
""")

registry = {
    "src/controllers/studentController.js": 0,
    "src/services/studentService.js":       1,
    "src/config/logger.js":                 2,
}

nodes, edges, embeddings = parse_codebase(repo_dir, registry)

print("=== NODES ===")
for n in nodes:
    print(f"  [{n['id']}] {n['canonical_path']}")
    print(f"       exports: {n.get('exported_names', [])}")

print()
print("=== EDGES ===")
for e in edges:
    print(f"  {e['source_id']} -> {e['target_id']}")
    print(f"       binding:        {e.get('binding', '')}")
    print(f"       called_names:   {e.get('called_names', [])}")
    print(f"       is_dead_import: {e.get('is_dead_import')}")

print()
print("=== ASSERTIONS ===")

# Build lookups
edge_map = {(e["source_id"], e["target_id"]): e for e in edges}

# controller(0) -> service(1): studentService is called → NOT dead
e_ctrl_svc = edge_map.get((0, 1))
assert e_ctrl_svc is not None, "Edge controller->service missing"
assert e_ctrl_svc["is_dead_import"] == False, f"Expected live import: {e_ctrl_svc}"
assert "findAll" in e_ctrl_svc["called_names"] or "findById" in e_ctrl_svc["called_names"], \
    f"Expected findAll/findById in called_names: {e_ctrl_svc}"
print("  [PASS] controller -> service: live import, called_names populated")

# controller(0) -> logger(2): logger imported but never called → dead
e_ctrl_log = edge_map.get((0, 2))
assert e_ctrl_log is not None, "Edge controller->logger missing"
assert e_ctrl_log["is_dead_import"] == True, f"Expected dead import: {e_ctrl_log}"
print("  [PASS] controller -> logger: dead import correctly detected")

print()
print("ALL ASSERTIONS PASSED")

# Cleanup
import shutil
shutil.rmtree(repo_dir)
