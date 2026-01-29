import json

class FeedbackStore:
    def __init__(self, filename='feedback_data.json'):
        self.filename = filename
        self.feedback_data = self._load_feedback()

    def _load_feedback(self):
        try:
            with open(self.filename, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"successful_examples": [], "failed_examples": []}

    def save_feedback(self):
        with open(self.filename, 'w') as f:
            json.dump(self.feedback_data, f, indent=2)

    def add_example(self, example: dict):
        """Add an example and invalidate cache"""
        if example not in self.feedback_data["successful_examples"]:
            self.feedback_data["successful_examples"].append(example)
            self.save_feedback()
           

#this block of code is used to save the feedback to a json file
#the feedback is saved to a json file
#the feedback is used in the agent.py file to train the agent




