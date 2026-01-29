import os
from transformers import AutoTokenizer, AutoModelForCausalLM

# --- CONFIGURATION ---
# Once you upload your model, change 'worker_base' to your HF Repo ID
# Example: "Aniket-a14/wizard-worker-v1"
MODELS = {
    "manager": os.getenv("MANAGER_MODEL_ID", "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"),
    "worker_base": os.getenv("WORKER_MODEL_ID", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
}
# ---------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

def download_model(role, model_name):
    print(f"⬇️  Downloading {role} ({model_name})...")
    save_path = os.path.join(MODELS_DIR, role)
    
    # Check if already exists to save time
    if os.path.exists(os.path.join(save_path, "config.json")):
        print(f"⏩ {role} already exists at {save_path}. Skipping.")
        return

    # Download with SSL robustness
    # Note: If you have SSL issues, run `set CURL_CA_BUNDLE=` first.
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    tokenizer.save_pretrained(save_path)
    
    model = AutoModelForCausalLM.from_pretrained(
        model_name, 
        trust_remote_code=True,
        low_cpu_mem_usage=True
    )
    model.save_pretrained(save_path)
    
    print(f"✅ Saved to: {save_path}\n")

if __name__ == "__main__":
    os.makedirs(MODELS_DIR, exist_ok=True)
    print(f"🚀 Starting offline model download to: {MODELS_DIR}\n")
    
    for role, name in MODELS.items():
        try:
            download_model(role, name)
        except Exception as e:
            print(f"❌ Failed to download {name}: {e}")
            
    print("🎉 All models ready! You can now run offline.")
