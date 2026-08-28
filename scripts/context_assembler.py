import os
import json
import argparse
from pathlib import Path

# --- Cálculo dinámico de la raíz del proyecto ---
REPO_ROOT = Path(__file__).resolve().parent.parent
# -------------------------------------------------------

def load_graph_data(graph_path=None):
    """Carga el JSON completo (metadata + files)."""
    if graph_path is None:
        graph_path = REPO_ROOT / "local_codegraph.json"
        
    if not os.path.exists(graph_path):
        print(f"Error: No se encontró {graph_path}. Ejecuta scripts/map_repository.py primero.")
        return None
    with open(graph_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def resolve_import_to_filepath(import_name, root_path=REPO_ROOT):
    parts = import_name.split('.')
    file_path = root_path.joinpath(*parts).with_suffix('.py')
    if file_path.exists(): return str(file_path)
    init_path = root_path.joinpath(*parts) / '__init__.py'
    if init_path.exists(): return str(init_path)
    return None

def get_markdown_language(filepath):
    ext, name = Path(filepath).suffix.lower(), Path(filepath).name.lower()
    if 'dockerfile' in name: return 'dockerfile'
    return {'.py': 'python', '.json': 'json', '.yml': 'yaml', '.yaml': 'yaml', '.md': 'markdown', '.sh': 'bash', '.js': 'javascript'}.get(ext, '')

def build_targeted_context(target_file, full_graph_data, is_audit_mode=False, output_file="targeted_context.md"):
    # Extraemos metadatos y el grafo de archivos para soportar la nueva estructura
    metadata = full_graph_data.get("metadata", {})
    graph = full_graph_data.get("files", full_graph_data) # El fallback (full_graph_data) cubre compatibilidad hacia atrás
    branch_name = metadata.get("branch", "unknown-branch")

    if target_file not in graph:
        print(f"Error: '{target_file}' no existe en el grafo de la rama '{branch_name}'. Verifica la ruta.")
        return

    node_data = graph[target_file]
    node_type = node_data.get("type", "python")
    callees, callers = set(), set()

    if node_type == "python":
        for imp in node_data.get("imports", []):
            resolved_path = resolve_import_to_filepath(imp)
            if resolved_path:
                rel_resolved = str(Path(resolved_path).relative_to(REPO_ROOT))
                if rel_resolved in graph: callees.add(rel_resolved)

        target_module_name = target_file.replace('/', '.').replace('.py', '')
        for filepath, data in graph.items():
            if filepath == target_file or data.get("type") != "python": continue
            if any(target_module_name in imp for imp in data.get("imports", [])): callers.add(filepath)

    print(f"Ensamblando contexto para: {target_file} (Tipo: {node_type})")
    print(f"Rama de Git: {branch_name}")
    print(f"Modo: {'AUDITORÍA (QA)' if is_audit_mode else 'PLANEACIÓN (SRE)'}")
    
    output_path = REPO_ROOT / output_file

    with open(output_path, 'w', encoding='utf-8') as out:
        out.write("### SYSTEM INSTRUCTIONS ###\n")
        out.write(f"CURRENT GIT BRANCH: `{branch_name}`\n") # <--- INYECCIÓN DE LA RAMA
        out.write(f"TARGET FILE: `{target_file}`\n\n")
        
        if is_audit_mode:
            out.write("ROLE: Act as my Principal QA Engineer and Architecture Auditor.\n")
            out.write("OBJECTIVE: Conduct a strict post-implementation review of the newly updated code. Verify that objectives were met and no regressions were introduced.\n")
            out.write("RULES:\n")
            out.write("1. Regression Profiling: Analyze callers/callees below. Did the changes break the interface for any caller?\n")
            out.write("2. DoD Verification: Strictly evaluate the new code against the Definition of Done provided below.\n")
            out.write("3. Anti-Fragility Check: Ensure no silent failures, memory leaks, or latent bugs were introduced.\n")
            out.write("4. Branch Context: Keep in mind the current branch context when evaluating the scope of the feature/fix.\n\n")
            out.write("EXPECTED OUTPUT:\n")
            out.write("(A) Goal Achievement Status [PASS / FAIL / PARTIAL]\n")
            out.write("(B) Regression Analysis\n")
            out.write("(C) Residual Risks & Code Smells\n")
            out.write("(D) Final Verdict (Merge or Hotfix)\n")
            out.write("###########################\n\n")
            out.write("### ⚠️ USER ACTION REQUIRED: PASTE THE DEFINITION OF DONE (DoD) BELOW THIS LINE ⚠️ ###\n")
            out.write("> DoD: [Pega aquí el DoD o el objetivo que queríamos lograr]\n\n")
        else:
            out.write("ROLE: Act as my Principal Software Engineer, Site Reliability Architect (SRE), and Chaos Engineer.\n")
            out.write("OBJECTIVE: Conduct a deep code audit and scientific debugging of the provided module.\n")
            out.write("RULES:\n")
            out.write("1. Boundary Analysis: Cross-reference the code with callers/callees. Do not break contracts.\n")
            out.write("2. Chaos Engineering: Assume network fails or DB drops. Ensure idempotency.\n")
            out.write("3. Zero Quick Patches: Track down the root cause and explain the logical flaw.\n")
            out.write("4. Branch Context: Ensure any proposed fixes or architectural plans align with the purpose of the current Git branch.\n\n")
            out.write("EXPECTED OUTPUT:\n")
            out.write("(A) Architecture Diagnosis\n")
            out.write("(B) Risks and Errors (Bugs/Blockers)\n")
            out.write("(C) Execution Action Plan (Task, Target File, Location, Action, DoD, Validation Method).\n")
            out.write("###########################\n\n")

        out.write(f"# Arquitectura Objetivo\n\n")
        
        if node_type == "python":
            out.write("## Módulos que dependen de este archivo (Callers):\n")
            for caller in callers: out.write(f"- `{caller}`\n")
            if not callers: out.write("- Ninguno.\n")
                
            out.write("\n## Dependencias internas (Callees):\n")
            for callee in callees: out.write(f"- `{callee}`\n")
            if not callees: out.write("- Ninguna.\n")
        else:
            out.write("> *Nota: El análisis automático de dependencias (Callers/Callees) aplica principalmente a archivos Python.*\n")

        files_to_attach = [target_file] + list(callers) + list(callees)
        
        out.write("\n\n# Código Fuente\n\n")
        for filepath in files_to_attach:
            md_lang = get_markdown_language(filepath)
            out.write(f"### FILE: {filepath}\n```{md_lang}\n")
            try:
                with open(REPO_ROOT / filepath, 'r', encoding='utf-8') as f:
                    out.write(f.read())
            except Exception as e:
                out.write(f"# Error leyendo archivo: {e}\n")
            out.write("\n```\n\n")

    print(f"\n¡Contexto generado en '{output_path}'!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Context Assembler para RAG de Código")
    parser.add_argument("target", help="Ruta relativa del archivo a analizar (ej. app/jobs/tips_reader.py)")
    parser.add_argument("--audit", action="store_true", help="Activa el modo de Auditoría/QA para revisar cambios realizados")
    args = parser.parse_args()
    
    graph_data = load_graph_data()
    if graph_data:
        build_targeted_context(args.target, graph_data, is_audit_mode=args.audit)
        