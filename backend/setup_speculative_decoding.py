import os
import subprocess
import sys
import shutil

def check_ollama():
    """Checks if Ollama CLI is accessible."""
    return shutil.which("ollama") is not None

def run_cmd(args):
    """Utility to run a CLI command and print status."""
    print(f"Running: {' '.join(args)}...")
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"❌ Error: {res.stderr.strip()}", file=sys.stderr)
        return False
    print("✅ Success!")
    return True

def main():
    print("=" * 60)
    print("        OLLAMA SPECULATIVE DECODING SETUP UTILITY        ")
    print("=" * 60)

    if not check_ollama():
        print("❌ Error: Ollama is not installed or not in system PATH.", file=sys.stderr)
        sys.exit(1)

    # 1. Ask/Determine target models
    target_model = "qwen2.5-coder:7b"
    draft_model = "qwen2.5-coder:1.5b"
    speculative_name = "qwen-speculative"

    print(f"Target Model: {target_model}")
    print(f"Draft Model:  {draft_model}")
    print(f"Creating Unified Model: {speculative_name}")
    print("-" * 60)

    # 2. Pull models
    print("Step 1: Pulling draft model...")
    if not run_cmd(["ollama", "pull", draft_model]):
        print("Failed to pull draft model. Aborting.", file=sys.stderr)
        sys.exit(1)

    print("\nStep 2: Pulling target model...")
    if not run_cmd(["ollama", "pull", target_model]):
        print("Failed to pull target model. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 3. Create Modelfile
    print("\nStep 3: Creating Modelfile configuration...")
    modelfile_content = f"""FROM {target_model}
ADAPTER {draft_model}
PARAMETER temperature 0.2
"""
    modelfile_path = "Modelfile"
    try:
        with open(modelfile_path, "w") as f:
            f.write(modelfile_content)
        print("Modelfile written successfully.")
    except Exception as e:
        print(f"❌ Failed to write Modelfile: {e}", file=sys.stderr)
        sys.exit(1)

    # 4. Create unified speculative model
    print("\nStep 4: Building speculative decoding model profile inside Ollama...")
    success = run_cmd(["ollama", "create", speculative_name, "-f", modelfile_path])
    
    # Cleanup
    if os.path.exists(modelfile_path):
        os.remove(modelfile_path)

    if success:
        print("\n🎉 Speculative decoding successfully configured!")
        print("To use it, update your .env file or environment variables:")
        print(f"   WORKER_MODEL_NAME={speculative_name}")
    else:
        print("\n❌ Failed to create speculative model.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)

if __name__ == "__main__":
    main()
