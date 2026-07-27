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

# The library set is declared to the model in `prompts.TOOLKIT`. Anything added
# here must be added there too, or the model will never know it can use it --
# which is exactly what happened with scikit-learn and statsmodels: both were
# installed for months while the prompt advertised only pandas and matplotlib,
# so generated code hand-rolled statistics that were sitting right there.
RUN pip install --no-cache-dir \
    "pandas==2.2.2" \
    "numpy==1.26.4" \
    "pyarrow==17.0.0" \
    "matplotlib==3.9.1" \
    "seaborn==0.13.2" \
    "plotly==5.23.0" \
    "scipy==1.14.0" \
    "statsmodels==0.14.2" \
    "scikit-learn==1.5.1" \
    "xgboost==2.1.1" \
    "lightgbm==4.5.0" \
    "lifelines==0.29.0" \
    "networkx==3.3" \
    "duckdb==1.1.0" \
    "openpyxl==3.1.5" \
    "xlsxwriter==3.2.0" \
    "tabulate==0.9.0" \
    "pillow==10.4.0"

# Geospatial is split out: it pulls GDAL/PROJ binaries and is the single largest
# contributor to image size, so a build that fails here still yields a usable
# image for every non-spatial question rather than no image at all.
RUN pip install --no-cache-dir "geopandas==1.0.1" "shapely==2.0.6" || \
    echo "geopandas unavailable; spatial analysis will fall back to runtime pip"

# Warm the matplotlib font cache so the first plot is not penalised by it.
RUN python -c "import matplotlib.pyplot as plt; plt.plot([0,1],[0,1]); plt.close('all')"

# Deliberately left as root *inside the container*. Switching to a fixed UID
# breaks writes to the bind-mounted workspace on Linux hosts, where the mount is
# owned by the invoking user. Containment comes from the runtime flags applied by
# SandboxPool instead: cap_drop=ALL, no-new-privileges, and memory/PID limits.
# Set SANDBOX_DOCKER_RUNTIME=runsc to add gVisor kernel isolation on top.
CMD ["sleep", "infinity"]
