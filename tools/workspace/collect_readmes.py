"""
collect_readmes.py — Zero-Install Context Extractor
Traverses local repositories, extracts README files, and compiles
them into strategically chunked context files optimized for LLM
upload limits and token constraints. Features smart minification
and guaranteed clean-slate overwriting on every execution.
"""

import os
import shutil
import re
import stat
import argparse
from pathlib import Path

EXCLUDED_DIRS = {
    ".codeflicker",
    ".git",
    ".kiro",
    ".molt",
    ".omo",
    ".pytest_cache",
    ".shell",
    ".vscode",
    "_molt",
    "_old_root_scripts",
    "_shell",
    "__pycache__",
    "Git",
    "Python",
    "Readme",
}

# Strategic threshold for chunking (Adjustable)
# 1500 lines is roughly 10,000 - 15,000 tokens.
MAX_LINES_PER_CHUNK = 1500


def force_remove_readonly(func, path, _):
    """Error handler for shutil.rmtree — clears read-only flag and retries."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def is_git_repo(path):
    return (path / ".git").exists()


def normalize_path(path: Path) -> Path:
    return Path(str(path).strip().strip('"')).resolve()


def get_readme_path(repo_path):
    """Case-insensitive search for a readme file."""
    for file in repo_path.iterdir():
        if file.is_file() and file.name.lower().startswith("readme"):
            return file
    return None


def repository_paths(workspace: Path):
    """Yield repositories stored directly in the workspace or below an owner folder."""
    for item in sorted(workspace.iterdir()):
        if not item.is_dir() or item.name in EXCLUDED_DIRS or item.name.startswith("."):
            continue
        if is_git_repo(item):
            yield item
            continue
        for child in sorted(item.iterdir()):
            if child.is_dir() and is_git_repo(child):
                yield child


def optimize_for_llm(text):
    """
    Cleans and minifies Markdown text specifically for AI ingestion.
    """
    # 1. Image Optimization: Convert ![Alt Text](url) to [IMAGE: Alt Text]
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'[IMAGE: \1]', text)
    
    # 2. HTML Image Optimization: Convert <img src="..." alt="Alt Text"> to [IMAGE: Alt Text]
    text = re.sub(r'<img[^>]+alt="([^"]+)"[^>]*>', r'[IMAGE: \1]', text)
    
    # 3. Whitespace Minification: Replace 3 or more consecutive newlines with exactly 2.
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # 4. Trailing Spaces: Remove invisible spaces at the end of lines
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Collect local repo READMEs into chunked context files.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()

    workspace = normalize_path(args.workspace)
    readme_dir = workspace / "Readme"

    print("-" * 50)
    print("Scanning and optimizing repositories for AI ingestion...")
    
    # Guaranteed Clean Slate: Delete and recreate the folder
    if readme_dir.exists():
        shutil.rmtree(readme_dir, onexc=force_remove_readonly)
    readme_dir.mkdir()

    repo_data = []
    total_lines = 0
    total_chars = 0

    # 1. Extraction & Optimization Phase
    for item in repository_paths(workspace):
        readme_file = get_readme_path(item)
        if readme_file:
            try:
                with open(readme_file, "r", encoding="utf-8-sig", errors="replace") as f:
                    raw_content = f.read()
                
                # Apply token-efficiency optimizations
                content = optimize_for_llm(raw_content)
                
                if not content:
                    continue

                repo_name = item.relative_to(workspace).as_posix().replace("/", "_")
                lines = content.count('\n') + 1
                total_lines += lines
                total_chars += len(content)

                repo_data.append({
                    "name": repo_name,
                    "content": content,
                    "lines": lines
                })

                # Export individual optimized reference file
                indiv_path = readme_dir / f"{repo_name}_README.md"
                with open(indiv_path, "w", encoding="utf-8") as out_f:
                    out_f.write(content)
                    
                print(f"[OPTIMIZED] {repo_name} (Lines: {lines})")

            except Exception as e:
                print(f"[ERROR] Could not process {item.name}: {e}")
        else:
            print(f"[SKIP]      {item.name} — No README found.")

    # 2. Intelligent Chunking Phase
    if not repo_data:
        print("\nNo README files found to process.")
        return

    print("\nCompiling strategically chunked LLM context files...")
    
    chunks = []
    current_chunk = []
    current_lines = 0
    
    for repo in repo_data:
        if current_lines + repo['lines'] > MAX_LINES_PER_CHUNK and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_lines = 0
            
        current_chunk.append(repo)
        current_lines += repo['lines']
        
    if current_chunk:
        chunks.append(current_chunk)

    # 3. Export Phase
    master_index_path = readme_dir / "_MASTER_INDEX.md"
    with open(master_index_path, "w", encoding="utf-8") as index_f:
        index_f.write("# MASTER REPOSITORY DIRECTORY\n")
        index_f.write("> Use this index to locate which file contains the context for a specific repository.\n\n")

        for i, chunk in enumerate(chunks, 1):
            part_filename = f"_PART_{i:02d}.md"
            part_path = readme_dir / part_filename
            
            # Update the Master Index
            index_f.write(f"### {part_filename}\n")
            
            # Write the individual chunk file
            with open(part_path, "w", encoding="utf-8") as part_f:
                part_f.write(f"# REPOSITORY CONTEXT: PART {i:02d} OF {len(chunks)}\n\n")
                
                for repo in chunk:
                    index_f.write(f"- {repo['name']}\n")
                    
                    part_f.write(f"## ==========================================\n")
                    part_f.write(f"## REPOSITORY: {repo['name']}\n")
                    part_f.write(f"## ==========================================\n\n")
                    part_f.write(f"{repo['content']}\n\n")
                    part_f.write(f"## END OF {repo['name']} CONTEXT\n\n\n")
                    
            index_f.write("\n")

    print("-" * 50)
    print("Extraction & Optimization Complete.")
    print(f"Total Repositories Processed : {len(repo_data)}")
    print(f"Total Combined Lines         : {total_lines}")
    print(f"Estimated Tokens Saved       : Compression applied.")
    print(f"Context Files Generated      : {len(chunks)} chunks")
    print(f"Index File Generated         : _MASTER_INDEX.md")
    print("-" * 50)

if __name__ == "__main__":
    main()
