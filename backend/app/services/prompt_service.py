import json
import random
from typing import List, Dict, Any
import os

class PromptService:
    def __init__(self, kb_path: str = "backend/prompts/knowledge_base.json"):
        self.kb_path = kb_path
        self.knowledge_base = self._load_kb()

    def _load_kb(self) -> Dict[str, Any]:
        try:
            # Adjust path if running from root or backend
            if not os.path.exists(self.kb_path):
                # Try relative to app/services/../../prompts
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                self.kb_path = os.path.join(base_dir, "prompts", "knowledge_base.json")
            
            with open(self.kb_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading knowledge base: {e}")
            return {"libraries": {}}

    def get_dynamic_prompt(self, instruction: str, columns: List[str]) -> str:
        """
        Generates a dynamic prompt based on instruction keywords and column context.
        """
        relevant_examples = []
        instruction_lower = instruction.lower()

        # Keyword matching strategy
        for lib, examples in self.knowledge_base.get("libraries", {}).items():
            for ex in examples:
                # Check if any keyword matches
                if any(k in instruction_lower for k in ex.get("keywords", [])):
                    relevant_examples.append(ex)
                # Also check library name itself
                if lib in instruction_lower:
                     relevant_examples.append(ex)

        # Fallback: if no matches, pick some generic pandas/matplotlib examples
        if not relevant_examples:
            relevant_examples.extend(self.knowledge_base["libraries"].get("pandas", [])[:2])
            relevant_examples.extend(self.knowledge_base["libraries"].get("matplotlib", [])[:1])

        # Deduplicate and limit to 5 examples to save tokens
        seen = set()
        unique_examples = []
        for ex in relevant_examples:
            if ex['code'] not in seen:
                unique_examples.append(ex)
                seen.add(ex['code'])
            if len(unique_examples) >= 5:
                break

        # Construct the Prompt
        examples_text = "\n".join([f"Task: {ex['task']}\nCode: {ex['code']}" for ex in unique_examples])
        
        prompt = f"""You are a Python data analysis assistant. 
1. The DataFrame is already loaded as 'df' with columns: {', '.join(columns)}
2. Return ONLY the code, no markdown, no explanations.
3. Use the provided libraries (pandas, numpy, scipy, sklearn, statsmodels, plotly, etc.) as needed.
4. If plotting, use plt.show() or fig.show().

Examples:
{examples_text}

Task: {instruction}
Code:"""
        return prompt

prompt_service = PromptService()
