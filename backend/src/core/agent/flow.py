from typing import Tuple, Optional
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
            # We assume 'hybrid' or 'local' wants to try local manager first
            path = settings.resolved_manager_path
            import os
            if os.path.exists(path):
                logger.info("Loading Local Manager Model...", path=path)
                try:
                    from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
                    import torch
                    
                    # Use float16 base for quantization if on GPU
                    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
                    
                    quant_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=dtype,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True,
                        llm_int8_enable_fp32_cpu_offload=True # Allow CPU offload if GPU full
                    )

                    tokenizer = AutoTokenizer.from_pretrained(path)
                    model = AutoModelForCausalLM.from_pretrained(
                        path, 
                        quantization_config=quant_config,
                        device_map="auto",
                        low_cpu_mem_usage=True,
                        offload_folder=settings.OFFLOAD_FOLDER # Folder for disk offload if needed
                    )
                    
                    self.local_manager = pipeline(
                        "text-generation", 
                        model=model, 
                        tokenizer=tokenizer,
                        # device=device # pipeline handles device via model placement above usually
                    )
                except Exception as e:
                    logger.error("Failed to load Local Manager", error=str(e))
                    return None
            else:
                # logger.warning("Local Manager path not found", path=path)
                return None
        return self.local_manager

    def run(self, instruction: str, df: pd.DataFrame) -> Tuple[str, str, Optional[str]]:
        logger.info("Starting Scientific Workflow", instruction=instruction)

        # 1. Planning Phase
        # We only do this if we have a strong model (Ollama/Hybrid)
        if settings.MODEL_TYPE in ["ollama", "hybrid"]:
            plan = self._create_plan(instruction, df)
            logger.info("Plan created", plan=plan)

            # Augment instruction with plan
            augmented_instruction = f"""
User Request: {instruction}

Approved Plan:
{plan}

Please execute this plan using Python.
"""
        else:
            augmented_instruction = instruction

        # 2. Execution Phase
        # We delegate the actual coding/running to the base agent
        result, code, image = self.execution_agent.run(augmented_instruction, df)

        # 3. Critique/Evaluation Phase (Optional for now)
        # Could feed 'result' back to LLM to ask "Does this answer the question?"

        return result, code, image

    def _create_plan(self, instruction: str, df: pd.DataFrame) -> str:
        """Generates a high-level analysis plan."""
        # Check Cache
        cache_key = response_cache.generate_key(
            instruction, str(df.columns.tolist()), str(df.shape)
        )
        cached_plan = response_cache.get(cache_key)
        if cached_plan:
            logger.info("Plan retrieved from cache")
            return cached_plan

        # Use local manager pipeline if available, else fallback
        llm_pipeline = self._get_manager_model()
        if not llm_pipeline:
            # Fallback to execution agent's LLM (Ollama) if local manager fails
            logger.info("Local Manager not loaded, falling back to Ollama")
            llm = self.execution_agent._get_llm()
        else:
            llm = None  # We use pipeline

        if not llm and not llm_pipeline:
            return "Proceed directly."

        try:
            prompt = create_planning_prompt(instruction, df)
            
            if llm_pipeline:
                # Generate using local transformer
                logger.info("Generating plan with Local Manager...")
                # Ensure we don't overflow context; Manager is 8B, usually handles 4k-8k tokens.
                response = llm_pipeline(
                    prompt, 
                    max_new_tokens=512, 
                    do_sample=True,
                    temperature=0.7,
                    pad_token_id=llm_pipeline.tokenizer.eos_token_id
                )
                plan = response[0]["generated_text"]
                # Strip prompt if included (transformers pipeline usually includes it)
                if plan.startswith(prompt):
                    plan = plan[len(prompt):].strip()
            else:
                # Original Ollama invocation
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
