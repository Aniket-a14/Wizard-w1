from typing import Tuple, Optional
import re
from ...config import settings
from ...utils.logging import logger
from ...utils.cache import response_cache
from .agent import DataAnalysisAgent
from ..prompts import create_planning_prompt
import pandas as pd


class ScientificAgent:
    """
    Orchestrates the Planning -> Execution -> Critique loop.
    "Level 100" Data Scientist behavior.
    """

    def __init__(self):
        self.execution_agent = DataAnalysisAgent()
        self.local_manager = None

    def _get_manager_model(self):
        """Lazy load the local Manager model (DeepSeek-Llama-8B)."""
        if self.local_manager is None:
            # Only load if we are in a mode that supports/needs it
            if settings.MODEL_TYPE not in ["local", "hybrid"]:
                return None

            path = settings.resolved_manager_path
            import os
            if os.path.exists(path):
                logger.info("Loading Local Manager Model...", path=path)
                try:
                    from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
                    import torch
                    
                    # Use float16 base for quantization if on GPU
                    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
                    
                    # Attempt 4-bit quantization
                    quant_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=dtype,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                        llm_int8_enable_fp32_cpu_offload=True
                    )
                    
                    tokenizer = AutoTokenizer.from_pretrained(path)
                    model = AutoModelForCausalLM.from_pretrained(
                        path, 
                        quantization_config=quant_config,
                        device_map="auto",
                        low_cpu_mem_usage=True,
                        offload_folder=settings.OFFLOAD_FOLDER
                    )
                except Exception as e:
                    logger.warning("4-bit quantization failed, falling back to float16", error=str(e))
                    # Fallback to standard float16
                    tokenizer = AutoTokenizer.from_pretrained(path)
                    model = AutoModelForCausalLM.from_pretrained(
                        path,
                        device_map="auto",
                        torch_dtype=torch.float16,
                        low_cpu_mem_usage=True,
                        offload_folder=settings.OFFLOAD_FOLDER
                    )
                    
                self.local_manager = pipeline(
                    "text-generation", 
                    model=model, 
                    tokenizer=tokenizer,
                )
            else:
                return None
        return self.local_manager

    def run(self, instruction: str, df: pd.DataFrame, mode: str = "planning", is_confirmed_plan: bool = False) -> Tuple[str, str, Optional[str], Optional[str], str]:
        """
        Returns: (Result, Code, Image, Thought, Status)
        Status: "completed" or "waiting_confirmation"
        """
        logger.info("Starting Scientific Workflow", instruction=instruction, mode=mode, confirmed=is_confirmed_plan)

        thought = None
        plan = ""
        augmented_instruction = instruction

        # 1. Planning Phase
        # Skip planning if we are in "fast" mode with a confirmed plan (or just re-executing)
        # BUT: Simpler logic is:
        # If is_confirmed_plan -> The instruction IS the plan. Skip planning.
        # If NOT is_confirmed_plan -> We need to Plan.
        
        should_plan = not is_confirmed_plan and settings.MODEL_TYPE in ["ollama", "hybrid"]

        if should_plan:
            raw_plan_response = self._create_plan(instruction, df)
            
            # Extract thought and plan
            thought_match = re.search(r"<thought>(.*?)</thought>", raw_plan_response, re.DOTALL)
            if thought_match:
                thought = thought_match.group(1).strip()
                plan = raw_plan_response.replace(thought_match.group(0), "").strip()
            else:
                plan = raw_plan_response
            
            logger.info("Plan created", thought_preview=thought[:50] if thought else "None")
            
            # CHECKPOINT: If mode is "planning", we stop here and ask for confirmation.
            if mode == "planning":
                return plan, "", None, thought, "waiting_confirmation"

            augmented_instruction = f"""
User Request: {instruction}

Approved Plan:
{plan}

Please execute this plan using Python.
"""
        elif is_confirmed_plan:
            # The instruction passed in IS the approved plan (plus context)
            augmented_instruction = instruction

        # 2. Execution Phase with Self-Correction
        max_retries = 2
        previous_error = None
        
        for attempt in range(max_retries + 1):
            result, code, image = self.execution_agent.run(augmented_instruction, df, previous_error=previous_error)
            
            if "Error executing code:" not in result:
                # Success!
                return result, code, image, thought, "completed"
            
            # Failure - Try to correct
            logger.warning(f"Execution failed (Attempt {attempt + 1})", error=result)
            previous_error = result
            
            if attempt == max_retries:
                logger.error("Max retries reached, returning failure.")
                return result, code, image, thought, "completed"

        return result, code, image, thought, "completed"

    def _create_plan(self, instruction: str, df: pd.DataFrame) -> str:
        """Generates a high-level analysis plan (including thoughts)."""
        # Check Cache
        cache_key = response_cache.generate_key(
            instruction, str(df.columns.tolist()), str(df.shape)
        )
        cached_plan = response_cache.get(cache_key)
        if cached_plan:
            logger.info("Plan retrieved from cache")
            return cached_plan

        llm_pipeline = self._get_manager_model()
        if not llm_pipeline:
            logger.info("Local Manager not loaded, falling back to Ollama")
            llm = self.execution_agent._get_llm()
        else:
            llm = None

        if not llm and not llm_pipeline:
            return "Proceed directly."

        try:
            prompt = create_planning_prompt(instruction, df)
            
            if llm_pipeline:
                logger.info("Generating plan with Local Manager...")
                response = llm_pipeline(
                    prompt, 
                    max_new_tokens=1024, # Increased for <thought> block
                    do_sample=True,
                    temperature=0.7,
                    pad_token_id=llm_pipeline.tokenizer.eos_token_id
                )
                plan = response[0]["generated_text"]
                if plan.startswith(prompt):
                    plan = plan[len(prompt):].strip()
            else:
                response = llm.invoke(prompt)
                plan = response.content

            # Cache Result
            response_cache.set(cache_key, plan)
            return plan
        except Exception as e:
            logger.warning("Planning failed, skipping", error=str(e))
            return "Proceed with analysis."


# Singleton for the higher-level agent
science_agent = ScientificAgent()
