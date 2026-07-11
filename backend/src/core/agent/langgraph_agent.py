from typing import Optional
import pandas as pd
from src.core.agent.agent import DataAnalysisAgent
from src.core.agent.council import TheCouncil


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
            
        try:
            prompt = create_planning_prompt(
                state.instruction, 
                state.df, 
                catalog=state.catalog, 
                mode=state.mode, 
                memory_context=memory_context
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
        
        worker_llm = self.execution_agent._get_worker_llm()
        few_shot = self.execution_agent.feedback_store.get_similar_examples(state.instruction)
        
        # Setup prompt with appropriate plan and error contexts
        worker_prompt = create_prompt(
            state.instruction,
            state.df,
            plan=state.plan,
            previous_error=state.error,
            catalog=state.catalog,
            few_shot_examples=few_shot
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

    def step_execute_code(self, state: WorkflowState) -> WorkflowState:
        """
        IPython Kernel Sandbox Execution Node.
        """
        logger.info("LangGraph Node: execute_code")
        
        if not state.code:
            state.error = "No code available to execute."
            state.status = "error"
            return state
            
        # 1. Guardrail Check before run
        is_safe, reason = GuardrailAgent.scan(state.code)
        if not is_safe:
            logger.warning("Guardrail blocked code execution", reason=reason)
            state.result = f"Blocked by guardrail: {reason}"
            state.status = "completed"
            return state

        # 2. Stateful IPython Execute
        result, _, plot_b64 = self.execution_agent._process_code(state.code, state.df)
        
        state.result = result
        state.image = plot_b64
        
        if "Error executing code:" in result or "Traceback" in result:
            state.error = result
            state.status = "correcting"
        else:
            state.status = "evaluating"
            
        return state

    def step_correct_error(self, state: WorkflowState) -> WorkflowState:
        """
        Dynamic self-correction routing (cyclic loop).
        """
        state.retry_count += 1
        max_retries = 3
        
        if state.retry_count > max_retries:
            logger.error("Max code correction retries exceeded")
            state.status = "error"
        else:
            logger.warning(f"Routing to self-correction loop (Attempt {state.retry_count})")
            state.status = "executing" # routes back to code_generate
            
        return state

    def step_evaluate(self, state: WorkflowState) -> WorkflowState:
        """
        Review/Evaluation Node. Scores result and runs The Council review.
        """
        logger.info("LangGraph Node: evaluate")
        
        try:
            # Score execution quality
            eval_result = Evaluator.score_execution(state.result)
            
            # Adjudicate via specialized council agents
            council_feedback = self.council.adjudicate(state.plan, state.code, state.result)
            
            # Formulate final response with transparent council reviews
            final_response = state.result + "\n\n### 🛡️ The Council's Review\n"
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
        
    def execute_workflow(self, state: WorkflowState) -> WorkflowState:
        """
        Run the complete compiled LangGraph flow sequentially.
        If paused at a 'waiting_approval' gateway, execution stops and returns state.
        """
        # Determine starting node
        if state.status == "init":
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
                state = self.step_evaluate(state)
            else:
                break
                
        return state


# Singleton Graph instance
langgraph_agent = LangGraphAgent()
