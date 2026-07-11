import re
import ast
from typing import Optional, Callable, List
import pandas as pd
import numpy as np
from src.config import settings
from src.utils.logging import logger
from src.core.agent.agent import DataAnalysisAgent
from src.core.prompts import create_replan_prompt, create_prompt, create_planning_prompt
from src.core.tools.guardrail import GuardrailAgent
from src.core.tools.evaluator import Evaluator
from src.core.agent.council import TheCouncil
from src.core.memory import working_memory
from src.core.semantic_cache import semantic_cache


class WorkflowState:
    """
    State dictionary representing the current state of the execution graph.
    """
    def __init__(self, instruction: str, df: pd.DataFrame, mode: str = "standard", catalog: Optional[dict] = None):
        self.instruction = instruction
        self.df = df
        self.mode = mode
        self.catalog = catalog
        
        self.plan = ""
        self.thought = ""
        self.code = ""
        self.result = ""
        self.image = None
        self.status = "init"  # init -> planning -> waiting_approval -> executing -> completed -> error
        self.retry_count = 0
        self.error = None
        
        # Iterative Execution & Trajectory Learning fields
        self.steps = []
        self.current_step_index = 0
        self.failed_code = ""
        self.failed_error = ""
        self.step_outputs = []
        
        # Details of tool execution if pending user approval
        self.pending_tool_approval = None  # None or {"tool": "web_search", "query": "..."}


class LangGraphAgent:
    """
    Stateful cyclical orchestrator mimicking a LangGraph multi-agent flow.
    Supports dynamic sub-agent planning, self-correction, and tool gating.
    """
    
    def __init__(self):
        self.execution_agent = DataAnalysisAgent()
        self.council = TheCouncil()
        
    def step_plan(self, state: WorkflowState) -> WorkflowState:
        """
        Planning Node (Supervisor). Generates thought process and plan.
        """
        logger.info("LangGraph Node: planning", instruction=state.instruction)
        
        # Retrieve context from working memory
        memory_context = working_memory.get_context_string(state.instruction)
        
        llm = self.execution_agent._get_llm()
        if not llm:
            state.plan = "Proceed directly with Python execution."
            state.status = "executing"
            return state
            
        # Check if this is a visualization customization query
        previous_code = None
        has_visual_keywords = any(kw in state.instruction.lower() for kw in {"color", "legend", "font", "size", "axis", "label", "grid", "visual", "title", "theme", "style", "plot"})
        if state.code and has_visual_keywords and ("plt." in state.code or "sns." in state.code):
            previous_code = state.code
            logger.info("Customizer: Visual refinement query detected. Feeding previous plot code to planner.")
            
        try:
            prompt = create_planning_prompt(
                state.instruction, 
                state.df, 
                catalog=state.catalog, 
                mode=state.mode, 
                memory_context=memory_context,
                previous_code=previous_code
            )
            response = llm.invoke(prompt).content
            
            # Extract thought process
            thought_match = re.search(r"<thought>(.*?)</thought>", response, re.DOTALL)
            if thought_match:
                state.thought = thought_match.group(1).strip()
                state.plan = response.replace(thought_match.group(0), "").strip()
            else:
                state.plan = response
                
            # Check for Gated Tools (like Web Search) inside planning
            if "SEARCH:" in state.plan:
                search_match = re.search(r'SEARCH:\s*"(.*?)"', state.plan)
                if search_match:
                    query = search_match.group(1)
                    # Pause flow for user approval
                    state.pending_tool_approval = {
                        "tool": "web_search",
                        "query": query,
                        "prompt": f"Wizard wants to search the web for: '{query}'. Allow?"
                    }
                    state.status = "waiting_approval"
                    logger.info("Planning paused for web search approval", query=query)
                    return state

            # Jupyter Step Extraction from generated plan
            steps = re.findall(r"(?:\d+\.\s+|-\s+)([^\n]+)", state.plan)
            steps = [s.strip() for s in steps if len(s.strip()) > 5]
            if len(steps) >= 2:
                state.steps = steps
                state.current_step_index = 0
                logger.info("Plan parsed into iterative steps", steps_count=len(steps))

            # If mode is planning, stop here and ask for plan execution approval
            if state.mode == "planning":
                state.status = "waiting_approval"
                state.pending_tool_approval = {
                    "tool": "execute_plan",
                    "plan": state.plan,
                    "prompt": "I have created the analysis plan. Please review and confirm execution."
                }
            else:
                state.status = "executing"
                
        except Exception as e:
            logger.error("Planning node failed", error=str(e))
            state.plan = f"1. Analyze dataset columns: {state.df.columns.tolist()}\n2. Complete request: {state.instruction}"
            state.status = "executing"
            
        return state

    def step_execute_search(self, state: WorkflowState, approved: bool) -> WorkflowState:
        """
        Executes web search if approved by user, then returns to planner.
        """
        if not approved or not state.pending_tool_approval:
            # User rejected the search or no tool is pending
            state.pending_tool_approval = None
            state.status = "executing"
            return state

        query = state.pending_tool_approval.get("query")
        state.pending_tool_approval = None
        
        logger.info("Executing approved web search", query=query)
        from src.core.tools.search import WebSearchTool
        
        try:
            search_tool = WebSearchTool()
            results = search_tool.search(query)
            
            # Replan with search results
            replan_prompt = create_replan_prompt(state.instruction, results, state.thought)
            llm = self.execution_agent._get_llm()
            if llm:
                replan_response = llm.invoke(replan_prompt).content
                state.plan = replan_response
                logger.info("Replanning complete with search results")
                
            state.status = "executing"
        except Exception as e:
            logger.error("Web search execution failed", error=str(e))
            state.status = "executing"
            
        return state

    def step_code_generate(self, state: WorkflowState) -> WorkflowState:
        """
        Coding Specialist Node. Generates Python code block to implement the plan.
        """
        logger.info("LangGraph Node: code_generate", attempt=state.retry_count)
        
        # Bypasses LLM generation if code is pre-loaded (e.g. from Semantic Cache)
        if state.code and not state.error:
            logger.info("Code block already pre-loaded. Bypassing worker LLM code generation.")
            return state
        
        # Determine the current instruction depending on whether we are executing step-by-step
        current_instruction = state.instruction
        if state.steps and state.current_step_index < len(state.steps):
            step_desc = state.steps[state.current_step_index]
            logger.info(f"Generating code for Step {state.current_step_index + 1} of {len(state.steps)}: {step_desc}")
            
            # Contextualize instruction for the current step in the notebook
            prior_outputs = "\n".join([f"# Step {idx+1} Output:\n# {out}" for idx, out in enumerate(state.step_outputs)])
            current_instruction = f"""Query: {state.instruction}

JUPYTER NOTEBOOK STEP {state.current_step_index + 1} of {len(state.steps)}:
=> {step_desc}

{prior_outputs}

Write python code ONLY for this step. Do not rewrite prior steps, just continue. Keep imports minimal."""

        worker_llm = self.execution_agent._get_worker_llm()
        few_shot = self.execution_agent.feedback_store.get_similar_examples(state.instruction)
        
        # Look up negative trajectories to avoid repeating bugs
        neg_examples = self._get_negative_examples(state.instruction, state.df.columns.tolist() if state.df is not None else None)
        instruction_with_warnings = current_instruction
        if neg_examples:
            instruction_with_warnings += "\n" + neg_examples

        # Setup prompt with appropriate plan and error contexts
        # Check for visual customization code pass-through
        previous_code = None
        has_visual_keywords = any(kw in state.instruction.lower() for kw in {"color", "legend", "font", "size", "axis", "label", "grid", "visual", "title", "theme", "style", "plot"})
        if state.code and has_visual_keywords and ("plt." in state.code or "sns." in state.code):
            previous_code = state.code

        worker_prompt = create_prompt(
            instruction_with_warnings, 
            state.df, 
            plan=state.plan, 
            previous_error=state.error if state.status == "correcting" else None, 
            catalog=state.catalog,
            few_shot_examples=few_shot,
            previous_code=previous_code
        )
        
        try:
            response = worker_llm.invoke(worker_prompt).content
            state.code = self.execution_agent._extract_code_block(response)
            logger.info("Generated code block successfully")
        except Exception as e:
            logger.error("Code generation failed", error=str(e))
            state.error = f"Generation error: {e}"
            state.status = "error"
            return state
            
        return state

    def step_execute_code(self, state: WorkflowState, on_stdout: Optional[Callable[[str], None]] = None) -> WorkflowState:
        """
        IPython Kernel Sandbox Execution Node.
        """
        logger.info("LangGraph Node: execute_code")
        
        if not state.code:
            state.error = "No code available to execute."
            state.status = "error"
            return state
            
        # 1. Deterministic AST Syntax & Security Validation with Local Repair
        success, repaired_code = self.attempt_code_repair(state.code)
        if success:
            state.code = repaired_code
            
        try:
            tree = ast.parse(state.code)
            
            # Security Import & Function Trace Scan
            banned_modules = {"os", "sys", "subprocess", "shutil", "socket"}
            for node in ast.walk(tree):
                # 1. Standard module imports checks
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split('.')[0] in banned_modules:
                            logger.warning("AST Guardrail blocked code execution", reason=f"Banned import: {alias.name}")
                            state.result = f"Blocked by guardrail: Banned import of '{alias.name}' is prohibited."
                            state.status = "completed"
                            return state
                elif isinstance(node, ast.ImportFrom):
                    if node.module and node.module.split('.')[0] in banned_modules:
                        logger.warning("AST Guardrail blocked code execution", reason=f"Banned import from: {node.module}")
                        state.result = f"Blocked by guardrail: Banned import from '{node.module}' is prohibited."
                        state.status = "completed"
                        return state
                        
                # 2. Dynamic obfuscation checks (eval, exec, __import__)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                        if func_name in {"eval", "exec", "__import__"}:
                            logger.warning("AST Security block: Dynamic code evaluation detected", function=func_name)
                            state.result = f"Blocked by guardrail: Use of dynamic code evaluation function '{func_name}' is prohibited."
                            state.status = "completed"
                            return state
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr == "__import__":
                            logger.warning("AST Security block: Dynamic __import__ attribute lookup detected")
                            state.result = "Blocked by guardrail: Dynamic import lookup is prohibited."
                            state.status = "completed"
                            return state
                            
                # 3. Path traversal file open breaks check
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                    if node.args:
                        path_node = node.args[0]
                        if isinstance(path_node, ast.Constant) and isinstance(path_node.value, str):
                            path_val = path_node.value
                            import os
                            clean_path = os.path.abspath(os.path.join("/workspace", path_val))
                            # Ensure it stays within /workspace or the host equivalent inside /app/workspace
                            if not (clean_path.startswith("/workspace") or clean_path.startswith("/app/workspace") or clean_path.startswith("/app/backend/workspace")):
                                logger.warning("AST Security block: File path traversal breakout attempt", path=path_val)
                                state.result = "Blocked by guardrail: Access to files outside the workspace directory is prohibited."
                                state.status = "completed"
                                return state
        except SyntaxError as se:
            syntax_error_msg = f"Syntax Error: {se.msg} on line {se.lineno}"
            logger.warning("AST Validation found syntax error", error=syntax_error_msg)
            state.error = f"Error executing code:\n{syntax_error_msg}"
            state.status = "correcting"
            return state

        # 2. Guardrail Check before run
        is_safe, reason = GuardrailAgent.scan(state.code)
        if not is_safe:
            logger.warning("Guardrail blocked code execution", reason=reason)
            state.result = f"Blocked by guardrail: {reason}"
            state.status = "completed"
            return state

        # 3. Stateful IPython Execute with stdout streaming callback
        result, _, plot_b64 = self.execution_agent._process_code(state.code, state.df, on_stdout)
        
        state.result = result
        state.image = plot_b64
        
        if "Error executing code:" in result or "Traceback" in result:
            state.error = result
            state.status = "correcting"
        elif plot_b64 and self.is_image_blank(plot_b64):
            logger.warning("Visual Guardrail detected blank/empty plot.")
            state.error = "Error executing code:\nGenerated visualization canvas is blank/empty. Ensure data is correctly passed to plotting axes (e.g. check variables, verify plt.plot/sns.scatterplot columns, or call plt.tight_layout())."
            state.status = "correcting"
        else:
            state.status = "evaluating"
            
        return state

    def step_correct_error(self, state: WorkflowState) -> WorkflowState:
        """
        Dynamic self-correction routing (cyclic loop).
        """
        # Record failed attempt details for trajectory learning
        state.failed_code = state.code
        state.failed_error = state.error

        state.retry_count += 1
        max_retries = 3
        
        if state.retry_count > max_retries:
            logger.error("Max code correction retries exceeded")
            state.status = "error"
        else:
            logger.warning(f"Routing to self-correction loop (Attempt {state.retry_count})")
            state.status = "executing" # routes back to code_generate
            
        return state

    async def step_evaluate(self, state: WorkflowState) -> WorkflowState:
        """
        Review/Evaluation Node. Scores result and runs The Council review.
        """
        logger.info("LangGraph Node: evaluate")
        
        try:
            # Handle intermediate outputs in Jupyter Step loop
            if state.steps:
                state.step_outputs.append(state.result)
                if state.current_step_index < len(state.steps) - 1:
                    logger.info(f"Finished Step {state.current_step_index + 1}. Transitioning to next step.")
                    state.current_step_index += 1
                    state.code = ""
                    state.error = None
                    state.retry_count = 0
                    state.status = "executing"
                    return state

            # Add to semantic cache if overall execution succeeded
            if state.code and not state.error:
                semantic_cache.add(state.instruction, state.df.columns.tolist(), state.code)
                
                # Save failure recovery trajectory if we healed
                if state.retry_count > 0 and getattr(state, "failed_code", None):
                    try:
                        from src.core.database import db_mgr
                        from src.core.semantic_cache import semantic_cache as sc
                        model = sc._get_model()
                        emb = model.encode(state.instruction.strip().lower()) if model else None
                        db_mgr.save_trajectory(
                            instruction=state.instruction,
                            columns=state.df.columns.tolist(),
                            failed_code=state.failed_code,
                            error_message=state.failed_error,
                            corrected_code=state.code,
                            embedding=emb
                        )
                        logger.info("Saved failure-correction trajectory to SQLite database.")
                    except Exception as e:
                        logger.error("Failed to save trajectory to database", error=str(e))

            # Score execution quality
            eval_result = Evaluator.score_execution(state.result)
            
            # Adjudicate via specialized council agents
            council_feedback = await self.council.adjudicate(state.plan, state.code, state.result)
            
            # Formulate final response with transparent council reviews
            final_response = state.result
            
            # Append Visual Insights if plot is present
            if state.image:
                logger.info("Plot generated. Fetching visual insights.")
                vision_desc = self.step_vision_explain(state.image)
                final_response += f"\n\n### 📊 Visual Insights\n{vision_desc}"
                
            final_response += "\n\n### 🛡️ The Council's Review\n"
            for review in council_feedback.get("reviews", []):
                agent_name = review["agent"]
                feedback_items = review.get("feedback", [])
                if feedback_items:
                    final_response += f"- **{agent_name}**: {', '.join(feedback_items)}\n"
                else:
                    final_response += f"- **{agent_name}**: ✅ No issues detected.\n"
                    
            state.result = final_response
            
            # Add to semantic memory
            working_memory.add_interaction(
                instruction=state.instruction,
                plan=state.plan,
                code=state.code,
                result=state.result,
                meta={"catalog": state.catalog, "quality_score": eval_result.get("score", 100)}
            )
            
            state.status = "completed"
        except Exception as e:
            logger.error("Evaluation node failed", error=str(e))
            state.status = "completed"
            
        return state

    def _get_negative_examples(self, query: str, columns: Optional[List[str]] = None) -> str:
        """
        Retrieves past matching failed trajectories from database as negative examples.
        """
        try:
            from src.core.database import db_mgr
            from src.core.semantic_cache import semantic_cache as sc
            entries = db_mgr.get_trajectory_entries(columns)
            if not entries:
                return ""
                
            model = sc._get_model()
            if not model:
                return ""
                
            query_vector = model.encode(query.strip().lower())
            
            best_match = None
            max_sim = -1.0
            
            for entry in entries:
                task_vector = entry.get("embedding")
                if task_vector is None or len(task_vector) == 0:
                    continue
                # Cosine similarity
                dot_product = np.dot(query_vector, task_vector)
                norm_q = np.linalg.norm(query_vector)
                norm_t = np.linalg.norm(task_vector)
                sim = dot_product / (norm_q * norm_t) if norm_q > 0 and norm_t > 0 else 0.0
                if sim > max_sim:
                    max_sim = sim
                    best_match = entry
                    
            if max_sim >= 0.90 and best_match:
                logger.info("Matched negative trajectory memory", similarity=round(max_sim, 4))
                return f"\n<failed_attempts_to_avoid>\nA similar query previously failed because of a syntax/runtime issue. Do NOT repeat this mistake.\nFailed Code:\n```python\n{best_match['failed_code']}\n```\nCompiler Error:\n{best_match['error_message']}\n\nCorrect Way to solve it:\n```python\n{best_match['corrected_code']}\n```\n</failed_attempts_to_avoid>\n"
        except Exception as e:
            logger.error("Error looking up negative trajectories", error=str(e))
        return ""

    def step_vision_explain(self, base64_image: str) -> str:
        """
        Queries local multimodal Ollama model to describe visual plots.
        """
        try:
            from langchain_ollama import ChatOllama
            from langchain_core.messages import HumanMessage
            
            vision_model_name = getattr(settings, "VISION_MODEL_NAME", "llava:7b")
            logger.info("Initializing Vision Model (ChatOllama)", model=vision_model_name)
            
            vision_llm = ChatOllama(
                model=vision_model_name,
                base_url=settings.OLLAMA_BASE_URL,
                temperature=0.2
            )
            
            # Create a multimodal message payload
            message = HumanMessage(
                content=[
                    {"type": "text", "text": "Describe this data visualization chart in 2-3 sentences. Explain the visible trend, the axes, and any key insights."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                    }
                ]
            )
            
            response = vision_llm.invoke([message]).content
            return response.strip()
        except Exception as e:
            logger.error("Failed to generate visual explanation", error=str(e))
            return "Generated data visualization plot based on columns."
            
    def attempt_code_repair(self, code: str) -> tuple[bool, str]:
        """
        Attempts deterministic local syntax and dependency auto-repair.
        Returns (success_flag, repaired_code).
        """
        # Pre-clean markdown code block boundaries if present
        clean_code = code.replace("```python", "").replace("```", "").strip()
        
        # 1. Check if the code parses as-is
        try:
            ast.parse(clean_code)
            return True, clean_code
        except SyntaxError:
            pass

        # 2. Heal missing common package imports
        common_imports = {
            "pd": "import pandas as pd",
            "np": "import numpy as np",
            "plt": "import matplotlib.pyplot as plt",
            "sns": "import seaborn as sns",
            "px": "import plotly.express as px",
            "go": "import plotly.graph_objects as go",
            "stats": "import scipy.stats as stats"
        }
        
        imports_to_add = []
        for token, imp in common_imports.items():
            if f"{token}." in clean_code and f"import {token}" not in clean_code and "from " not in clean_code:
                imports_to_add.append(imp)
                
        if imports_to_add:
            repaired_code = "\n".join(imports_to_add) + "\n" + clean_code
            try:
                ast.parse(repaired_code)
                logger.info("Healed missing imports in generated code locally", imports=imports_to_add)
                return True, repaired_code
            except Exception:
                pass
                
        return False, clean_code
        
    def is_image_blank(self, base64_str: str) -> bool:
        """
        Deterministically identifies blank or broken visualizations by analyzing pixel variance.
        """
        if not base64_str:
            return True
        try:
            import base64
            from io import BytesIO
            from PIL import Image
            import numpy as np
            
            # Decode b64 image
            img_data = base64.b64decode(base64_str)
            img = Image.open(BytesIO(img_data)).convert("RGB")
            
            # Convert to numpy array for variance analysis
            img_arr = np.array(img)
            
            # Compute standard deviation across all pixels
            std_dev = np.std(img_arr)
            
            # If standard deviation is extremely low, the image has virtually no visual features
            if std_dev < 1.5:
                return True
                
            # Check unique color count: if there's only 1 or 2 unique colors, it's blank
            colors = img.getcolors(maxcolors=256)
            if colors is not None and len(colors) <= 2:
                return True
                
            return False
        except Exception as e:
            logger.error("Failed to analyze image quality", error=str(e))
            return False
        
    def is_simple_query(self, instruction: str) -> bool:
        """
        Deterministically identifies simple queries to bypass planning steps.
        """
        instruction_lower = instruction.lower().strip()
        simple_keywords = [
            "show first", "show top", "show head", "display head", "display first",
            "show last", "show bottom", "show tail", "display tail", "display last",
            "show columns", "list columns", "what columns", "column names",
            "shape of", "how many rows", "number of rows", "dataset dimensions",
            "show table", "preview dataset", "preview table"
        ]
        return any(kw in instruction_lower for kw in simple_keywords)

    async def execute_workflow(self, state: WorkflowState) -> WorkflowState:
        """
        Run the complete compiled LangGraph flow sequentially.
        If paused at a 'waiting_approval' gateway, execution stops and returns state.
        """
        # Determine starting node & perform routing / cache lookup
        if state.status == "init":
            # 1. Semantic Cache Check
            cached_code = semantic_cache.lookup(state.instruction, state.df.columns.tolist())
            if cached_code:
                state.plan = "Bypassed planning (Semantic Cache Hit)."
                state.code = cached_code
                state.status = "executing"
            # 2. Router Check
            elif self.is_simple_query(state.instruction):
                logger.info("Router: Simple query detected. Bypassing planner node.")
                state.plan = f"Retrieve and display the requested rows or dataset columns directly for instruction: {state.instruction}"
                state.status = "executing"
            # 3. Default Planning
            else:
                state.status = "planning"
            
        # Graph execution loop
        while state.status not in ["completed", "error", "waiting_approval"]:
            if state.status == "planning":
                state = self.step_plan(state)
            elif state.status == "executing":
                state = self.step_code_generate(state)
                if state.status == "executing": # Check if node changed status
                    state = self.step_execute_code(state)
            elif state.status == "correcting":
                state = self.step_correct_error(state)
            elif state.status == "evaluating":
                state = await self.step_evaluate(state)
            else:
                break
                
        return state


# Singleton Graph instance
langgraph_agent = LangGraphAgent()
