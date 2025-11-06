import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

# ===============================
# University Project Commit Script (Python version)
# ===============================

# --- Configuration ---
is_test = True   # <-- Set to False for live Git commits
original_folder = r"E:\uni"
trimmed_folder  = r"E:\uni-test"
repo_root       = r"E:\Projects\university-projects"
preview_file    = "commit-preview.txt"

# --- Date Settings ---
cutoff = datetime(2017, 3, 1, tzinfo=timezone.utc)
fallback_date = datetime(2017, 3, 2, tzinfo=timezone.utc)

# --- Helper: check git availability ---
def ensure_git_available():
    try:
        subprocess.run(["git", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Git not found! Please install Git and ensure it's available in your PATH.")
        sys.exit(1)

if not is_test:
    ensure_git_available()

# --- Init ---
with open(preview_file, "w", encoding="utf-8") as f:
    f.write("")

# Step 1: Build lookup of original file dates
original_lookup = {}
original_files = []

for root, _, files in os.walk(original_folder):
    for name in files:
        full_path = os.path.join(root, name)
        relative = os.path.relpath(full_path, original_folder)
        mtime = datetime.utcfromtimestamp(os.path.getmtime(full_path)).replace(tzinfo=timezone.utc)
        original_lookup[relative] = mtime
        original_files.append((relative, mtime))

original_files.sort(key=lambda x: x[1])

# Step 2: Compute first valid date after cutoff
first_valid_date = next((dt for _, dt in original_files if dt >= cutoff), fallback_date)

# Step 3: Group trimmed files
grouped_commits = {}

for root, _, files in os.walk(trimmed_folder):
    for name in files:
        full_path = os.path.join(root, name)
        relative = os.path.relpath(full_path, trimmed_folder)

        # Resolve commit date
        if relative in original_lookup:
            original_date = original_lookup[relative]
            if original_date < cutoff:
                commit_date = cutoff.replace(
                    month=original_date.month,
                    day=original_date.day,
                    hour=original_date.hour,
                    minute=original_date.minute,
                    second=original_date.second
                )
            else:
                commit_date = original_date
        else:
            commit_date = fallback_date

        # Extract module path
        parts = re.split(r"[\\/]", relative)
        year_part = next((p for p in parts if re.match(r"^Year\s*\d+$", p)), None)
        if year_part and parts.index(year_part) + 1 < len(parts):
            module_folder = parts[parts.index(year_part) + 1]
            module_path = f"{year_part}\\{module_folder}"
        else:
            year_part = "Unknown Year"
            module_folder = "Unknown Module"
            module_path = f"{year_part}\\{module_folder}"

        group_key = f"{commit_date.strftime('%Y-%m-%d')}|{module_path}"
        grouped_commits.setdefault(group_key, []).append(full_path)

# Step 4–5: Process commit groups
module_commit_counts = {}
with open(preview_file, "a", encoding="utf-8") as f:

    for group_key in sorted(grouped_commits.keys()):
        files = grouped_commits[group_key]
        day, module_path = group_key.split("|")
        commit_date = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        year_part, module_folder = module_path.split("\\", 1)
        match = re.match(r"^(.+?)\s*-\s*(.+)$", module_folder)
        if match:
            module_code, module_name = match.groups()
        else:
            module_code = module_folder.strip()
            module_name = module_folder.strip()

        # Commit counter
        module_key = f"{year_part}|{module_folder}"
        module_commit_counts[module_key] = module_commit_counts.get(module_key, 0) + 1
        commit_number = module_commit_counts[module_key]

        # File type summary
        type_counts = {}
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            type_counts[ext] = type_counts.get(ext, 0) + 1
        type_summary = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items()))

        formatted_files = "\n".join("  - " + os.path.relpath(f, trimmed_folder) for f in files)
        commit_message = f"{module_code} - {module_name} ({year_part}) Commit #{commit_number} - {len(files)} files on {day}\nIncludes: {type_summary}"

        f.write(f"--- Commit Preview for {day} ---\n{commit_message}\nFiles:\n{formatted_files}\n\n")

        if not is_test:
            # --- Live mode ---
            os.chdir(repo_root)
            for file in files:
                rel_path = os.path.relpath(file, trimmed_folder)
                target_path = os.path.join(repo_root, rel_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                if not os.path.exists(target_path):
                    shutil.copy2(file, target_path)
                subprocess.run(["git", "add", "--", target_path], check=True)

            git_date = commit_date.isoformat()
            env = os.environ.copy()
            env["GIT_AUTHOR_DATE"] = git_date
            env["GIT_COMMITTER_DATE"] = git_date

            subprocess.run(["git", "commit", "-m", commit_message], check=True, env=env)
            subprocess.run(["git", "push"], check=True, env=env)
        else:
            f.write("⚙️ [TEST MODE] No files copied or commits made.\n")

# Step 6: Summary
summary_lines = ["\n--- Commit Totals per Module-Year ---", "Year\tModule Code\tModule Name\tTotal Commits"]
total_commits = 0

for key in sorted(module_commit_counts.keys()):
    year_part, module_folder = key.split("|", 1)
    match = re.match(r"^(.+?)\s*-\s*(.+)$", module_folder)
    if match:
        module_code, module_name = match.groups()
    else:
        module_code = module_folder.strip()
        module_name = module_folder.strip()
    count = module_commit_counts[key]
    total_commits += count
    summary_lines.append(f"{year_part}\t{module_code}\t{module_name}\t{count}")

summary_lines.append(f"\nTotal Commits Across All Modules: {total_commits}")

with open(preview_file, "a", encoding="utf-8") as f:
    f.write("\n".join(summary_lines))

print("✅ Test mode complete." if is_test else "🚀 Live commits complete.")
