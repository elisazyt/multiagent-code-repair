# Python 3.11 matches what requirements.txt is actually validated against;
# newer Python versions risk missing prebuilt wheels for torch/pyserini/tree-sitter.
FROM python:3.11-slim

# Prevents Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1

# Keeps Python from buffering stdout and stderr to avoid situations where
# the application crashes without emitting any logs due to buffering.
ENV PYTHONUNBUFFERED=1

# System dependencies required by the pipeline itself, not just Python:
# - git, subversion: Defects4J checks out projects from either VCS depending on the project
# - perl, cpanminus: Defects4J's own framework is Perl-based
# - build-essential: compiling Python C-extensions without prebuilt wheels (tree-sitter etc.)
# - curl, wget, unzip, ca-certificates, gnupg: installing Joern, Defects4J, and Temurin's apt repo
# - ant, maven: different Defects4J projects use different build systems
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    subversion \
    perl \
    cpanminus \
    build-essential \
    curl \
    wget \
    unzip \
    ca-certificates \
    gnupg \
    ant \
    maven \
    && rm -rf /var/lib/apt/lists/*

# Debian's own repos only carry one or two current JDKs per release and drop old ones (e.g.
# neither "trixie" nor "bookworm" carry openjdk-11-jdk any more) - use Eclipse Temurin's own
# apt repo instead, which maintains all LTS versions (11, 21) independent of the base distro.
RUN wget -qO - https://packages.adoptium.net/artifactory/api/gpg/key/public | gpg --dearmor -o /usr/share/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    temurin-11-jdk \
    temurin-21-jdk \
    && rm -rf /var/lib/apt/lists/*

# Java 11 is required by Defects4J for compiling/running older project versions.
# get_java11_env() (src/defects4j_utils.py) reads this env var directly on Linux instead of
# the macOS-only `java_home -v 11` lookup it uses for local development. Temurin's install
# directory name includes the CPU architecture (e.g. temurin-11-jdk-arm64 vs -amd64), so
# symlink it to a stable, architecture-independent path.
RUN ln -s /usr/lib/jvm/temurin-11-jdk-* /opt/java11
ENV JAVA11_HOME=/opt/java11

# Install Defects4J: clone the framework, install its Perl dependencies, then run init.sh to
# download per-project support libraries. This is done at build time so the resulting image
# is self-contained and container startup is fast, at the cost of a large, slow build.
RUN git clone https://github.com/rjust/defects4j /opt/defects4j \
    && cd /opt/defects4j \
    && cpanm --installdeps . \
    && ./init.sh
ENV DEFECTS4J_HOME=/opt/defects4j
ENV PATH="${DEFECTS4J_HOME}/framework/bin:${PATH}"

# Install Joern (code property graph tool used for context retrieval).
# NOTE: verify this matches Joern's current official install instructions before relying on
# this build - the exact script name/flags may have changed since this was written.
RUN curl -L "https://github.com/joernio/joern/raw/master/joern-install.sh" -o joern-install.sh \
    && chmod +x joern-install.sh \
    && ./joern-install.sh --install-dir=/opt/joern --without-shell-completion \
    && rm joern-install.sh
# main.py reads this env var directly (no fallback - it must be set).
ENV JOERN_EXECUTABLE=/opt/joern/joern-cli/joern

WORKDIR /projects

# Download dependencies as a separate step to take advantage of Docker's caching.
# Leverage a cache mount to /root/.cache/pip to speed up subsequent builds.
# Leverage a bind mount to requirements.txt to avoid having to copy them into
# into this layer.
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=bind,source=requirements.txt,target=requirements.txt \
    python -m pip install -r requirements.txt

# Copy the source code into the container.
COPY src/ ./src/

ENTRYPOINT ["python3", "src/main.py"]

# No CMD, the user should always provide their own args after the image name
# to specify their configs and the project/bug ID to patch (refer to README)

# To open interactive terminal (may be useful for debugging):
# docker run -it --entrypoint bash <image-name>