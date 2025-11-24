from transformers import AutoTokenizer, AutoModelForCausalLM, Trainer, TrainingArguments, DataCollatorForLanguageModeling
from datasets import load_dataset, Dataset
import pandas as pd


df = pd.read_csv("./dataset/instruction_code_dataset.csv")
dataset = Dataset.from_pandas(df)


model_name = "gpt2"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)

tokenizer.pad_token = tokenizer.eos_token

def tokenize_function(examples):
    texts = [
        f"Instruction: {instr}\nCode: {code}"
        for instr, code in zip(examples["instruction"], examples["code"])
    ]
    return tokenizer(texts, truncation=True, padding="max_length", max_length=128)

tokenized_dataset = dataset.map(tokenize_function, batched=True)

data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

training_args = TrainingArguments(
    output_dir="./results",
    num_train_epochs=3,
    per_device_train_batch_size=4,
    save_steps=500,
    save_total_limit=2,
    logging_steps=100,
)


trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_dataset,
    data_collator=data_collator,
)


trainer.train()
model.save_pretrained("./fine_tuned_model")
tokenizer.save_pretrained("./fine_tuned_model")


#this block of code is used to train the model
#it trains the model on the dataset
#the model is then saved to the fine_tuned_model folder
#the model is then used to execute the code


