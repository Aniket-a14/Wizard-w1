import os
from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments, DataCollatorForLanguageModeling
from datasets import load_dataset, Dataset
import pandas as pd
import torch
from peft import LoraConfig, get_peft_model, TaskType

# Configuration
MODEL_NAME = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
DATASET_PATH = "backend/dataset/instruction_code_dataset.csv"
OUTPUT_DIR = "backend/fine_tuned_model_full"
LOG_DIR = "backend/logs_full"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.pad_token = tokenizer.eos_token

def tokenize_function(examples):
    texts = [
        f"Instruction: {instr}\nCode: {code}"
        for instr, code in zip(examples["instruction"], examples["code"])
    ]
    return tokenizer(texts, truncation=True, padding="max_length", max_length=128)

if __name__ == "__main__":
    print(f"Loading dataset from {DATASET_PATH}...")
    df = pd.read_csv(DATASET_PATH)
    dataset = Dataset.from_pandas(df)

    # Full Dataset Split (95/5)
    dataset = dataset.train_test_split(test_size=0.05)

    print("Loading model...")
    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)

    # LoRA Configuration
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM, 
        inference_mode=False, 
        r=64,          # High rank for detailed adaptation
        lora_alpha=128, 
        lora_dropout=0.05, # Lower dropout for stable high-rank training
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"], # Target all linear layers
        bias="none",
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    print("Tokenizing dataset...")
    # Optimized for Ryzen 5 5600G (6 cores/12 threads)
    tokenized_dataset = dataset.map(tokenize_function, batched=True, num_proc=8)

    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=3,              # Full 3 epochs
        per_device_train_batch_size=4,   # Reduced to 4 for RTX 2060 Super (8GB VRAM)
        gradient_accumulation_steps=8,   # Increased to maintain effective batch size = 32
        per_device_eval_batch_size=4,
        save_steps=1000,
        save_total_limit=3,
        logging_dir=LOG_DIR,
        logging_steps=50,
        evaluation_strategy="steps",
        eval_steps=1000,
        fp16=True,                       # FP16 is perfect for RTX 20 series
        gradient_checkpointing=True,
        dataloader_num_workers=4,        # Reduced to 4 to prevent 16GB RAM OOM
        report_to="none",                # Disable wandb for now
    )

    # Required when using gradient checkpointing with LoRA
    if training_args.gradient_checkpointing:
        model.enable_input_require_grads()

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset["train"],
        eval_dataset=tokenized_dataset["test"],
        data_collator=data_collator,
    )

    print("Starting full training...")
    trainer.train()

    print(f"Saving model to {OUTPUT_DIR}...")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
