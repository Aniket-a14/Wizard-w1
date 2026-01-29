from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
)
from datasets import Dataset
import pandas as pd
import torch

# Configuration
MODEL_NAME = "Qwen/Qwen2.5-Coder-1.5B-Instruct"
DATASET_PATH = "backend/dataset/instruction_code_dataset.csv"
OUTPUT_DIR = "backend/fine_tuned_model"
LOG_DIR = "backend/logs"


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

    # Train/Test Split (95/5 for 500k rows)
    # OPTIMIZATION: Subsample for local training (1k rows = ~3.5 hours on CPU/Low-GPU)
    dataset = dataset.shuffle(seed=42).select(range(1000))
    dataset = dataset.train_test_split(test_size=0.05)

    model = AutoModelForCausalLM.from_pretrained(MODEL_NAME)

    # LoRA Configuration
    from peft import LoraConfig, get_peft_model, TaskType

    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        inference_mode=False,
        r=8,
        lora_alpha=32,
        lora_dropout=0.1,
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    print("Tokenizing dataset...")
    tokenized_dataset = dataset.map(tokenize_function, batched=True, num_proc=4)

    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    training_args = TrainingArguments(
        output_dir="./results",
        num_train_epochs=1,  # Reduced to 1 for local feasibility
        per_device_train_batch_size=1,  # Keep small
        gradient_accumulation_steps=16,
        per_device_eval_batch_size=1,
        save_steps=2000,
        save_total_limit=2,
        logging_dir=LOG_DIR,
        logging_steps=100,
        evaluation_strategy="steps",
        eval_steps=2000,
        fp16=torch.cuda.is_available(),  # Re-enable FP16 for memory savings
        gradient_checkpointing=True,  # Critical for low VRAM
        dataloader_num_workers=0,
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

    print("Starting training...")
    trainer.train()

    print(f"Saving model to {OUTPUT_DIR}...")
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)


# this block of code is used to train the model
# it trains the model on the dataset
# the model is then saved to the fine_tuned_model folder
# the model is then used to execute the code
