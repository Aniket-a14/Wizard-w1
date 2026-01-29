import sys
import os
import pandas as pd

# Ensure backend directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Modern Imports (Src Architecture)
from src.core.agent.flow import science_agent
from src.config import settings
from feedback_store import FeedbackStore

def load_dataset_local(file_path: str) -> pd.DataFrame:
    """Helper to load dataset locally for CLI."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    df = pd.read_csv(file_path)
    if df.empty:
        raise ValueError("Dataset is empty")
    return df

def main():
    try:
        print(f"\nHi! I'm {settings.APP_NAME}, your data analysis assistant (CLI Mode).")
        print(f"Environment: {settings.ENV}")
        
        file_path = input("Enter dataset file path (CSV): ")
        
        try:
            df = load_dataset_local(file_path)
        except Exception as e:
            print(f"Error loading file: {e}")
            return

        feedback_store = FeedbackStore()
        
        print("\nDataset loaded successfully!")
        print(f"Shape: {df.shape}")
        print("\nColumns:")
        print(df.columns.tolist())
        print("\nType 'help' for available commands or 'exit' to quit.")
        
        while True:
            instruction = input("\nBot: What data analysis task can I help you with? ").strip()
            if instruction.lower() == 'exit':
                break
            elif instruction.lower() == 'help':
                print("\nAvailable commands:")
                print("- exit: Quit the program")
                print("- help: Show this help message")
                continue
            
            print("\nProcessing your request...")
            
            try:
                # Synchronous execution via Science Agent
                result, code, image = science_agent.run(instruction, df)
                
                print("\nResult:", result)
                if image:
                    print("(Chart generated and saved)")
                
                # Feedback Loop
                while True:
                    feedback = input("\nWas this result correct? (y/n): ").lower()
                    if feedback in ['y', 'yes', 'n', 'no']:
                        break
                    print("Please enter 'y' or 'n'")
                    
                if feedback in ['y', 'yes']:
                    example = {
                        "task": instruction,
                        "code": code
                    }
                    feedback_store.add_example(example)
                    print("Great! Added to successful examples.")
                else:
                    correct_code = input("What would be the correct code? (press enter to skip): ")
                    if correct_code.strip():
                        correct_example = {
                            "task": instruction,
                            "code": correct_code
                        }
                        feedback_store.add_example(correct_example)
                    print("Thank you for the feedback!")
                    
            except Exception as e:
                print(f"Error executing task: {e}")
                continue
                
    except KeyboardInterrupt:
        print("\nProgram terminated by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
