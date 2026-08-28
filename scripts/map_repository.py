import os
import ast
import json
import fnmatch
import subprocess
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

EXCLUDE_DIRS = {
    '.git', '.pytest_cache', '__pycache__', 'venv', 'env', '.venv', '.venv_app',
    'node_modules', 'dist', 'build', '.deps', '.dumbledoer', 'rollbacks', 'scratch',
    '.vscode', 'ruff_cache', '.checkpoints', '.codegraph', '.obsidian', '_jobs', 
    '_agents', 'archive', 'routes', 'schemas', 'knowledge'
}

REPO_ROOT = Path(__file__).resolve().parent.parent
INCLUDE_TESTS = False

# ==========================================
# FUNCIONES DE AST Y ANALIZADORES (Sin cambios)
# ==========================================
class CodeGraphBuilder(ast.NodeVisitor):
    def __init__(self, filepath):
        self.filepath = str(filepath)
        self.classes = []
        self.functions = []
        self.imports = []

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module if node.module else ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}")
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        class_info = {"name": node.name, "line": node.lineno, "methods": []}
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                class_info["methods"].append(item.name)
        self.classes.append(class_info)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if not any(node.name in c["methods"] for c in self.classes):
            self.functions.append({"name": node.name, "line": node.lineno})
        self.generic_visit(node)

def analyze_python_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as file:
        try:
            tree = ast.parse(file.read(), filename=str(filepath))
            builder = CodeGraphBuilder(filepath)
            builder.visit(tree)
            return {
                "type": "python",
                "imports": builder.imports,
                "classes": builder.classes,
                "functions": builder.functions
            }
        except SyntaxError:
            return {"type": "python", "error": "SyntaxError"}
        except Exception as e:
            return {"type": "python", "error": str(e)}

def analyze_dockerfile(filepath):
    docker_data = {"type": "docker", "base_images": [], "exposed_ports": [], "entrypoint": None, "cmd": None}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as file:
        for line in file:
            line = line.strip()
            if line.startswith("FROM "): docker_data["base_images"].append(line.replace("FROM ", "").strip())
            elif line.startswith("EXPOSE "): docker_data["exposed_ports"].append(line.replace("EXPOSE ", "").strip())
            elif line.startswith("ENTRYPOINT "): docker_data["entrypoint"] = line.replace("ENTRYPOINT ", "").strip()
            elif line.startswith("CMD "): docker_data["cmd"] = line.replace("CMD ", "").strip()
    return docker_data

def analyze_config_file(filepath):
    ext = filepath.suffix.lower()
    config_data = {"type": "config_file", "format": ext, "top_level_keys": []}
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as file:
            if ext == '.json':
                data = json.load(file)
                if isinstance(data, dict): config_data["top_level_keys"] = list(data.keys())
            elif ext in ['.yml', '.yaml'] and HAS_YAML:
                data = yaml.safe_load(file)
                if isinstance(data, dict): config_data["top_level_keys"] = list(data.keys())
            else:
                config_data["info"] = "YAML parser not installed or unsupported format"
    except Exception as e:
        config_data["error"] = str(e)
    return config_data

def analyze_generic_file(filepath):
    try:
        return {"type": "generic_text", "size_bytes": filepath.stat().st_size}
    except Exception:
        return {"type": "generic", "error": "Unreadable"}

# ==========================================
# LÓGICA DE GIT, FILTRADO Y MAPEO
# ==========================================
def get_git_branch(repo_path: Path) -> str:
    """Obtiene el nombre de la rama actual de Git."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown-branch"

def load_gitignore_patterns(root: Path) -> list:
    gitignore_path = root / '.gitignore'
    patterns = []
    if gitignore_path.exists():
        with open(gitignore_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.endswith('/'): line = line[:-1]
                    patterns.append(line)
    return patterns

def is_ignored(path: Path, gitignore_patterns: list) -> bool:
    rel_path_obj = path.relative_to(REPO_ROOT)
    rel_path = str(rel_path_obj)
    parts = rel_path_obj.parts
    
    if any(part.startswith('.') and part != '.' for part in parts[:-1]): return True
    if any(part in EXCLUDE_DIRS for part in parts): return True
    if not INCLUDE_TESTS and parts and parts[0] == 'tests': return True

    for pattern in gitignore_patterns:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(path.name, pattern): return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts): return True
    return False

def build_repository_graph(root_dir=REPO_ROOT):
    graph = {}
    root_path = Path(root_dir)
    gitignore_patterns = load_gitignore_patterns(root_path)
    current_branch = get_git_branch(root_path)

    print(f"Iniciando mapeo integral en la raíz: {root_path} (Rama: {current_branch})...")
    
    mapped_count = 0
    for filepath in root_path.rglob('*'):
        if not filepath.is_file() or is_ignored(filepath, gitignore_patterns):
            continue
            
        filename, ext = filepath.name, filepath.suffix.lower()
        if ext == '.py': file_data = analyze_python_file(filepath)
        elif filename == 'Dockerfile' or ext == '.dockerfile': file_data = analyze_dockerfile(filepath)
        elif ext in ['.json', '.yml', '.yaml']: file_data = analyze_config_file(filepath)
        elif ext in ['.md', '.txt', '.sh']: file_data = analyze_generic_file(filepath)
        else: continue
        
        if file_data:
            rel_path = str(filepath.relative_to(root_path))
            graph[rel_path] = file_data
            mapped_count += 1

    # Estructura del JSON enriquecida
    output_data = {
        "metadata": {
            "branch": current_branch,
            "mapped_files_count": mapped_count
        },
        "files": graph
    }

    output_file = root_path / "local_codegraph.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4)
        
    print(f"\n¡Grafo construido! Se mapearon {mapped_count} archivos en {output_file}.")
    return output_data

if __name__ == "__main__":
    build_repository_graph()
    