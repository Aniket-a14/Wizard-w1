# Execution sandbox image.
#
# Generated analysis code runs here, never in the API process. The library set is
# pre-installed rather than pip-installed on demand: the default PLOT_FORMAT is
# "html", which needs plotly, so a bare image forced a network install before the
# very first chart could render -- and that install is impossible when
# SANDBOX_NETWORK_DISABLED is on.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib

WORKDIR /workspace

RUN pip install --no-cache-dir \
    "pandas==2.2.2" \
    "numpy==1.26.4" \
    "matplotlib==3.9.1" \
    "seaborn==0.13.2" \
    "scipy==1.14.0" \
    "plotly==5.23.0" \
    "scikit-learn==1.5.1" \
    "statsmodels==0.14.2" \
    "pyarrow==17.0.0" \
    "openpyxl==3.1.5" \
    "tabulate==0.9.0"

# Warm the matplotlib font cache so the first plot is not penalised by it.
RUN python -c "import matplotlib.pyplot as plt; plt.plot([0,1],[0,1]); plt.close('all')"

# Deliberately left as root *inside the container*. Switching to a fixed UID
# breaks writes to the bind-mounted workspace on Linux hosts, where the mount is
# owned by the invoking user. Containment comes from the runtime flags applied by
# SandboxPool instead: cap_drop=ALL, no-new-privileges, and memory/PID limits.
# Set SANDBOX_DOCKER_RUNTIME=runsc to add gVisor kernel isolation on top.
CMD ["sleep", "infinity"]
