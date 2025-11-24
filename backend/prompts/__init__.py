from .utils import create_prompt, create_simple_prompt
from feedback_store import FeedbackStore

def get_feedback_examples():
    """Get successful feedback examples (cached)"""
    feedback_store = FeedbackStore()
    return feedback_store.feedback_data.get("successful_examples", [])

__all__ = ['create_prompt', 'create_simple_prompt', 'get_feedback_examples']