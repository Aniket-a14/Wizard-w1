import pandas as pd
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import ast
from difflib import SequenceMatcher
from tqdm import tqdm
import numpy as np

def calculate_similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def is_syntax_valid(code):
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False

def evaluate():
    print("Loading model and tokenizer...")
    model_path = "./backend/fine_tuned_model"
    try:
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model = AutoModelForCausalLM.from_pretrained(model_path)
    except Exception as e:
        print(f"Error loading model: {e}")
        return

    # Use GPU if available
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    print(f"Using device: {device}")

    print("Loading dataset...")
    try:
        df = pd.read_csv("./backend/dataset/instruction_code_dataset.csv")
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return

    # Sample for evaluation (to save time, or use all for full stats)
    # Using 50 samples for quick feedback
    sample_size = min(50, len(df))
    print(f"Evaluating on {sample_size} random samples...")
    test_df = df.sample(n=sample_size, random_state=42)

    results = {
        "exact_match": 0,
        "syntax_valid": 0,
        "similarity_scores": []
    }

    print("\nStarting evaluation metrics generation...")
    print("-" * 50)

    for index, row in tqdm(test_df.iterrows(), total=len(test_df)):
        instruction = row['instruction']
        ground_truth = row['code']

        prompt = f"Instruction: {instruction}\nCode:"
        
        inputs = tokenizer(prompt, return_tensors="pt").to(device)
        
        with torch.no_grad():
            outputs = model.generate(
                inputs.input_ids, 
                max_new_tokens=128, 
                num_return_sequences=1,
                pad_token_id=tokenizer.eos_token_id,
                do_sample=False # Greedy decoding for deterministic evaluation
            )
        
        generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Extract the code part (naive extraction based on prompt structure)
        if "Code:" in generated_text:
            generated_code = generated_text.split("Code:")[1].strip()
        else:
            generated_code = generated_text.replace(prompt, "").strip()

        # 1. Exact Match
        if generated_code == ground_truth:
            results["exact_match"] += 1

        # 2. Syntax Validity
        if is_syntax_valid(generated_code):
            results["syntax_valid"] += 1

        # 3. Similarity
        sim = calculate_similarity(generated_code, ground_truth)
        results["similarity_scores"].append(sim)

    # Calculate Aggregates
    metrics = {
        "Accuracy (Exact Match)": f"{(results['exact_match'] / sample_size) * 100:.2f}%",
        "Syntax Success Rate": f"{(results['syntax_valid'] / sample_size) * 100:.2f}%",
        "Average Code Similarity": f"{np.mean(results['similarity_scores']) * 100:.2f}%",
        "Model": "fine_tuned_gpt2"
    }

    print("\n" + "="*30)
    print(" EVALUATION REPORT ")
    print("="*30)
    for k, v in metrics.items():
        print(f"{k}: {v}")
    print("="*30)

    # Save detailed report
    with open("evaluation_report.txt", "w") as f:
        f.write("Model Evaluation Report\n")
        f.write("=======================\n\n")
        for k, v in metrics.items():
            f.write(f"{k}: {v}\n")

if __name__ == "__main__":
    evaluate()
