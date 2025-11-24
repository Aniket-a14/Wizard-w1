from pathlib import Path

# Model configuration
# Model configuration
MODEL_TYPE = "hybrid"  # Options: "ollama", "local", "hybrid"
MODEL_NAME = "deepseek-r1" # Used if MODEL_TYPE is "ollama" or "hybrid" (complex)
MODEL_PATH = "./fine_tuned_model" # Used if MODEL_TYPE is "local" or "hybrid" (simple)
TEMPERATURE = 0.7
MAX_TOKENS = 2000

# Path configuration
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
FEEDBACK_DIR = BASE_DIR / "feedback"


DATA_DIR.mkdir(exist_ok=True)
FEEDBACK_DIR.mkdir(exist_ok=True)

# Analysis configuration
ALLOWED_OPERATIONS = [
    'head', 'tail', 'describe', 'info',
    'mean', 'sum', 'count', 'std', 'corr',
    'plot', 'hist', 'scatter', 'line'
]

# Plotting configuration
PLOT_STYLE = 'seaborn'
FIGURE_SIZE = (10, 6)
